"""Live session execution for RD collection workflows."""

from __future__ import annotations

import math
import random
import select
import sys
import time
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Self
from typing import cast

import serial
from rich.console import Console

from vassago.collection.rd import quick_qc
from vassago.collection.rd import session as collection_session
from vassago.collection.rd import ui as collection_ui
from vassago.collection.rd import visualizer
from vassago.collection.rd.config import WindowRange
from vassago.collection.rd.paths import resolve_repo_path
from vassago.firmware.mmwave import config as mmwave_config
from vassago.firmware.mmwave.protocol import MmwavePacket
from vassago.firmware.mmwave.protocol import MmwavePacketParser
from vassago.firmware.mmwave.protocol import SmokeTestSummary
from vassago.firmware.mmwave.protocol import SmokeTestSummaryAccumulator
from vassago.firmware.mmwave.protocol import summarize_packets
from vassago.firmware.mmwave.smoke_test import DEFAULT_READ_SIZE
from vassago.firmware.mmwave.smoke_test import DEFAULT_READ_TIMEOUT_SECONDS
from vassago.firmware.mmwave.smoke_test import send_config
from vassago.firmware.mmwave.smoke_test import validate_cli_session

if TYPE_CHECKING:
    from pathlib import Path

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - POSIX terminals are the primary target.
    termios = None
    tty = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

type TerminalAttributes = (
    list[int | list[bytes | int]] | list[int | list[bytes]] | list[int | list[int]]
)

console = Console()
CAPTURE_LOOP_SLEEP_SECONDS = 0.01
CAPTURE_POLL_TIMEOUT_SECONDS = 0.05
GO_PROMPT_STYLE = "bold white on #0f9d58"
COUNTDOWN_NUMBER_STYLES = (
    "bold #38bdf8",
    "bold #84cc16",
    "bold #facc15",
    "bold #fb923c",
    "bold #ef4444",
)
SYSTEM_RANDOM = random.SystemRandom()


@dataclass(slots=True, frozen=True)
class AttemptPlan:
    """Concrete runtime plan for one collection attempt."""

    countdown_duration_s: float
    capture_window: WindowRange
    target_window: WindowRange
    marked_window_deadline_s: float
    capture_start_delay_s: float
    end_mark_key: str


@dataclass(slots=True, frozen=True)
class TakeCaptureResult:
    """Raw UART bytes plus runtime windows for one take."""

    raw_capture: bytes
    capture_window: WindowRange
    target_window: WindowRange
    marked_window: WindowRange | None


@dataclass(slots=True, frozen=True)
class RunSessionSummary:
    """Compact summary returned after one collection run stops."""

    manifest_path: Path
    session_id: str
    session_status: str
    accepted_take_count: int
    remaining_take_count: int


@dataclass(slots=True, frozen=True)
class ReviewedTakeCapture:
    """Capture output plus the first-line analysis used by run_session."""

    capture_result: TakeCaptureResult
    summary: SmokeTestSummary
    qc_decision: quick_qc.QuickQcDecision


type CaptureByteConsumer = Callable[[bytes], None]
type CapturePacketConsumer = Callable[[tuple[MmwavePacket, ...]], None]


@dataclass(slots=True, frozen=True)
class _CaptureTimeline:
    """Absolute timestamps that drive one capture attempt."""

    go_at: float
    capture_start_at: float
    capture_end_at: float
    target_end_at: float


@dataclass(slots=True)
class _CaptureLoopState:
    """Mutable flags for one running capture loop."""

    last_countdown_value: int | None = None
    capture_started: bool = False
    go_announced: bool = False
    target_end_announced: bool = False


@dataclass(slots=True)
class _CaptureRuntime:
    """Mutable runtime state shared across one active capture loop."""

    connection: serial.Serial
    read_size: int
    raw_capture: bytearray
    byte_consumers: tuple[CaptureByteConsumer, ...]
    packet_parser: MmwavePacketParser | None
    packet_consumers: tuple[CapturePacketConsumer, ...]


def run_session(
    manifest_path: Path,
    *,
    read_size: int = DEFAULT_READ_SIZE,
    enable_visualizer: bool = False,
) -> RunSessionSummary:
    """Run or resume one collection session until completion or interruption."""
    resolved_manifest_path = resolve_repo_path(manifest_path)
    manifest = collection_session.load_manifest(resolved_manifest_path)
    session_id = _require_str(manifest, "session_id")

    if collection_session.count_remaining_takes(manifest) == 0:
        collection_session.update_session_status(
            manifest,
            status=collection_session.SESSION_STATUS_COMPLETED,
        )
        collection_session.write_manifest(
            manifest_path=resolved_manifest_path,
            manifest=manifest,
        )
        return build_run_summary(
            manifest_path=resolved_manifest_path,
            manifest=manifest,
        )

    collection_session.update_session_status(
        manifest,
        status=collection_session.SESSION_STATUS_IN_PROGRESS,
    )
    collection_session.write_manifest(
        manifest_path=resolved_manifest_path,
        manifest=manifest,
    )

    try:
        _configure_radar(manifest)
        _run_take_loop(
            manifest_path=resolved_manifest_path,
            manifest=manifest,
            read_size=read_size,
            enable_visualizer=enable_visualizer,
        )
    except BaseException:
        collection_session.update_session_status(
            manifest,
            status=collection_session.SESSION_STATUS_INTERRUPTED,
        )
        collection_session.write_manifest(
            manifest_path=resolved_manifest_path,
            manifest=manifest,
        )
        raise

    final_status = (
        collection_session.SESSION_STATUS_COMPLETED
        if collection_session.count_remaining_takes(manifest) == 0
        else collection_session.SESSION_STATUS_INTERRUPTED
    )
    collection_session.update_session_status(manifest, status=final_status)
    collection_session.write_manifest(
        manifest_path=resolved_manifest_path,
        manifest=manifest,
    )
    console.print(f"Collection session stopped: {session_id} ({final_status})")
    return build_run_summary(
        manifest_path=resolved_manifest_path,
        manifest=manifest,
    )


def build_run_summary(
    *,
    manifest_path: Path,
    manifest: collection_session.JsonObject,
) -> RunSessionSummary:
    """Build the final summary from one manifest."""
    return RunSessionSummary(
        manifest_path=manifest_path,
        session_id=_require_str(manifest, "session_id"),
        session_status=_require_str(manifest, "session_status"),
        accepted_take_count=collection_session.count_accepted_takes(manifest),
        remaining_take_count=collection_session.count_remaining_takes(manifest),
    )


def _run_take_loop(
    *,
    manifest_path: Path,
    manifest: collection_session.JsonObject,
    read_size: int,
    enable_visualizer: bool,
) -> None:
    """Drive the operator state machine across all remaining takes."""
    data_port = _require_str(manifest, "data_port")
    data_baudrate = _require_int(manifest, "data_baudrate")

    with serial.Serial(
        port=data_port,
        baudrate=data_baudrate,
        timeout=DEFAULT_READ_TIMEOUT_SECONDS,
    ) as connection:
        time.sleep(DEFAULT_READ_TIMEOUT_SECONDS)
        connection.reset_input_buffer()

        while True:
            take = collection_session.next_pending_take(manifest)
            if take is None:
                return

            attempt_plan = _build_attempt_plan(manifest)
            take_index = _require_int(take, "take_index")
            take_id = _require_str(take, "take_id")
            batch_size = collection_session.count_total_takes(manifest)
            collection_ui.render_take_state(
                console,
                take_id=take_id,
                take_index=take_index,
                batch_size=batch_size,
                countdown_duration_s=attempt_plan.countdown_duration_s,
                target_window_duration_s=(
                    attempt_plan.target_window.end_s
                    - attempt_plan.target_window.start_s
                ),
                end_mark_key=attempt_plan.end_mark_key,
                accepted_take_count=collection_session.count_accepted_takes(manifest),
                remaining_take_count=collection_session.count_remaining_takes(manifest),
            )

            action = collection_ui.prompt_take_action(take_id=take_id)
            if action == collection_ui.TAKE_ACTION_QUIT:
                return

            reviewed_capture = review_capture_take(
                connection,
                attempt_plan=attempt_plan,
                read_size=read_size,
                enable_visualizer=enable_visualizer,
            )
            collection_ui.render_quick_qc(
                console,
                decision=reviewed_capture.qc_decision,
            )
            if not reviewed_capture.qc_decision.accepted:
                decision = collection_ui.prompt_rejected_take_action(take_id=take_id)
                if decision == collection_ui.TAKE_DECISION_QUIT:
                    return
                continue

            collection_ui.render_capture_summary(
                console,
                summary=reviewed_capture.summary,
                capture_window=reviewed_capture.capture_result.capture_window,
                target_window=reviewed_capture.capture_result.target_window,
                marked_window=reviewed_capture.capture_result.marked_window,
            )

            decision = collection_ui.prompt_take_decision(take_id=take_id)
            if decision == collection_ui.TAKE_DECISION_RETRY:
                continue
            if decision == collection_ui.TAKE_DECISION_QUIT:
                return

            raw_uart_path = collection_session.build_take_output_path(
                manifest_path=manifest_path,
                take=take,
            )
            raw_uart_path.write_bytes(reviewed_capture.capture_result.raw_capture)
            collection_session.accept_take(
                manifest=manifest,
                take=take,
                raw_uart_path=raw_uart_path,
                capture_window=reviewed_capture.capture_result.capture_window,
                target_window=reviewed_capture.capture_result.target_window,
                marked_window=reviewed_capture.capture_result.marked_window,
            )
            collection_session.write_manifest(
                manifest_path=manifest_path,
                manifest=manifest,
            )


def review_capture_take(
    connection: serial.Serial,
    *,
    attempt_plan: AttemptPlan,
    read_size: int,
    enable_visualizer: bool = False,
) -> ReviewedTakeCapture:
    """Capture one take and run the current summary/QC pipeline inline."""
    packet_parser = MmwavePacketParser()
    packets: list[MmwavePacket] = []
    visualizer_session = visualizer.start_visualizer(enabled=enable_visualizer)
    try:
        capture_result = capture_take(
            connection,
            attempt_plan=attempt_plan,
            read_size=read_size,
            packet_parser=packet_parser,
            packet_consumers=(
                packets.extend,
                visualizer_session.consume_packets,
            ),
        )
    finally:
        visualizer_session.close()

    summary = summarize_packets(
        packets=packets,
        bytes_read=len(capture_result.raw_capture),
        invalid_packet_count=packet_parser.invalid_packet_count,
    )
    qc_decision = quick_qc.evaluate_capture(
        summary=summary,
        capture_window=capture_result.capture_window,
        target_window=capture_result.target_window,
        marked_window=capture_result.marked_window,
        marked_window_end_grace_s=(
            attempt_plan.marked_window_deadline_s - attempt_plan.target_window.end_s
        ),
    )
    return ReviewedTakeCapture(
        capture_result=capture_result,
        summary=summary,
        qc_decision=qc_decision,
    )


def capture_take(
    connection: serial.Serial,
    *,
    attempt_plan: AttemptPlan,
    read_size: int,
    byte_consumers: Iterable[CaptureByteConsumer] = (),
    packet_parser: MmwavePacketParser | None = None,
    packet_consumers: Iterable[CapturePacketConsumer] = (),
) -> TakeCaptureResult:
    """Capture one attempt with fixed countdown, GO, and hidden capture start."""
    console.print("state: countdown")
    console.print(
        f"control: wait for GO, then press {attempt_plan.end_mark_key} to mark end"
    )

    timeline = _build_capture_timeline(attempt_plan)
    loop_state = _CaptureLoopState()
    runtime = _CaptureRuntime(
        connection=connection,
        read_size=read_size,
        raw_capture=bytearray(),
        byte_consumers=tuple(byte_consumers),
        packet_parser=packet_parser,
        packet_consumers=tuple(packet_consumers),
    )

    original_timeout = connection.timeout
    connection.timeout = _capture_poll_timeout(original_timeout)

    try:
        with _MarkedWindowRecorder(
            capture_duration_s=attempt_plan.capture_window.end_s,
            target_window=attempt_plan.target_window,
            end_mark_key=attempt_plan.end_mark_key,
        ) as marker:
            _run_capture_loop(
                attempt_plan=attempt_plan,
                runtime=runtime,
                timeline=timeline,
                loop_state=loop_state,
                marker=marker,
            )
            marker.poll(elapsed_seconds=attempt_plan.capture_window.end_s)
            marked_window = marker.window
    finally:
        connection.timeout = original_timeout

    console.print("capture_window ended")
    trailing_bytes = read_available_bytes(connection, read_size=read_size)
    _record_capture_bytes(runtime, chunk=trailing_bytes)
    return TakeCaptureResult(
        raw_capture=bytes(runtime.raw_capture),
        capture_window=attempt_plan.capture_window,
        target_window=attempt_plan.target_window,
        marked_window=marked_window,
    )


def _build_capture_timeline(attempt_plan: AttemptPlan) -> _CaptureTimeline:
    """Return the absolute timestamps that drive one capture attempt."""
    timeline_start = time.perf_counter()
    capture_start_at = timeline_start + attempt_plan.capture_start_delay_s
    capture_duration_s = (
        attempt_plan.capture_window.end_s - attempt_plan.capture_window.start_s
    )
    return _CaptureTimeline(
        go_at=timeline_start + attempt_plan.countdown_duration_s,
        capture_start_at=capture_start_at,
        capture_end_at=capture_start_at + capture_duration_s,
        target_end_at=capture_start_at + attempt_plan.target_window.end_s,
    )


def _run_capture_loop(
    *,
    attempt_plan: AttemptPlan,
    runtime: _CaptureRuntime,
    timeline: _CaptureTimeline,
    loop_state: _CaptureLoopState,
    marker: _MarkedWindowRecorder,
) -> None:
    """Drive the live capture loop until the fixed capture window ends."""
    while True:
        now = time.perf_counter()
        _update_countdown(loop_state=loop_state, timeline=timeline, now=now)
        _maybe_start_capture(
            connection=runtime.connection,
            timeline=timeline,
            loop_state=loop_state,
            now=now,
        )
        _maybe_render_go_prompt(
            timeline=timeline,
            loop_state=loop_state,
            now=now,
        )
        if not loop_state.capture_started:
            time.sleep(CAPTURE_LOOP_SLEEP_SECONDS)
            continue
        if _capture_window_finished(
            attempt_plan=attempt_plan,
            runtime=runtime,
            timeline=timeline,
            loop_state=loop_state,
            marker=marker,
            now=now,
        ):
            return


def _update_countdown(
    *,
    loop_state: _CaptureLoopState,
    timeline: _CaptureTimeline,
    now: float,
) -> None:
    """Render countdown ticks until GO has been announced."""
    if loop_state.go_announced:
        return
    loop_state.last_countdown_value = _emit_countdown_tick(
        now=now,
        go_at=timeline.go_at,
        last_countdown_value=loop_state.last_countdown_value,
    )


def _maybe_start_capture(
    *,
    connection: serial.Serial,
    timeline: _CaptureTimeline,
    loop_state: _CaptureLoopState,
    now: float,
) -> None:
    """Reset the host input buffer once the hidden capture start is reached."""
    if loop_state.capture_started or now < timeline.capture_start_at:
        return
    loop_state.capture_started = True
    connection.reset_input_buffer()


def _maybe_render_go_prompt(
    *,
    timeline: _CaptureTimeline,
    loop_state: _CaptureLoopState,
    now: float,
) -> None:
    """Render GO exactly once when the countdown is complete."""
    if loop_state.go_announced or now < timeline.go_at:
        return
    loop_state.go_announced = True
    _render_go_prompt()


def _capture_window_finished(
    *,
    attempt_plan: AttemptPlan,
    runtime: _CaptureRuntime,
    timeline: _CaptureTimeline,
    loop_state: _CaptureLoopState,
    marker: _MarkedWindowRecorder,
    now: float,
) -> bool:
    """Process one active-capture iteration and return whether capture is done."""
    _poll_capture_marker(
        marker=marker,
        capture_duration_s=attempt_plan.capture_window.end_s,
        capture_start_at=timeline.capture_start_at,
    )
    if not loop_state.target_end_announced and now >= timeline.target_end_at:
        loop_state.target_end_announced = True
        console.print("target_window ended")
    if now >= timeline.capture_end_at:
        return True

    chunk = runtime.connection.read(runtime.read_size)
    _record_capture_bytes(runtime, chunk=chunk)
    _poll_capture_marker(
        marker=marker,
        capture_duration_s=attempt_plan.capture_window.end_s,
        capture_start_at=timeline.capture_start_at,
    )
    return False


def _poll_capture_marker(
    *,
    marker: _MarkedWindowRecorder,
    capture_duration_s: float,
    capture_start_at: float,
) -> None:
    """Poll the end-mark recorder with the current elapsed capture time."""
    marker.poll(
        elapsed_seconds=min(
            capture_duration_s,
            time.perf_counter() - capture_start_at,
        ),
    )


def _record_capture_bytes(
    runtime: _CaptureRuntime,
    *,
    chunk: bytes,
) -> None:
    """Append one raw chunk and broadcast it to any inline consumers."""
    if not chunk:
        return
    runtime.raw_capture.extend(chunk)
    for consumer in runtime.byte_consumers:
        consumer(chunk)
    _broadcast_capture_packets(runtime, chunk=chunk)


def _broadcast_capture_packets(
    runtime: _CaptureRuntime,
    *,
    chunk: bytes,
) -> None:
    """Parse one raw chunk once and fan out any complete packets."""
    if runtime.packet_parser is None:
        return
    packets = tuple(runtime.packet_parser.feed(chunk))
    if not packets:
        return
    for consumer in runtime.packet_consumers:
        consumer(packets)


def _render_go_prompt() -> None:
    """Render a clear GO cue without adding extra layout noise."""
    console.print(" GO ", style=GO_PROMPT_STYLE)


def _render_countdown_tick(visible_value: int) -> None:
    """Render a simple countdown line with only the number color changing."""
    console.print(
        f"countdown: [{_countdown_number_style(visible_value)}]{visible_value}[/]"
    )


def _countdown_number_style(visible_value: int) -> str:
    """Return the numeric highlight color for the visible countdown second."""
    clamped_value = min(len(COUNTDOWN_NUMBER_STYLES), max(1, visible_value))
    style_index = len(COUNTDOWN_NUMBER_STYLES) - clamped_value
    return COUNTDOWN_NUMBER_STYLES[style_index]


def summarize_raw_capture(raw_capture: bytes) -> SmokeTestSummary:
    """Parse one captured UART window into the same summary used by smoke-test."""
    summary_accumulator = SmokeTestSummaryAccumulator()
    summary_accumulator.feed(raw_capture)
    return summary_accumulator.build_summary()


def read_available_bytes(
    connection: serial.Serial,
    *,
    read_size: int,
) -> bytes:
    """Drain bytes already buffered by the host without waiting for more data."""
    buffered = bytearray()
    original_timeout = connection.timeout
    connection.timeout = 0.0
    try:
        while True:
            chunk = connection.read(read_size)
            if not chunk:
                return bytes(buffered)
            buffered.extend(chunk)
    finally:
        connection.timeout = original_timeout


def _build_attempt_plan(manifest: collection_session.JsonObject) -> AttemptPlan:
    """Build one randomized runtime plan from the manifest snapshot."""
    config_snapshot = _require_dict(manifest, "config_snapshot")
    runtime = _require_dict(config_snapshot, "runtime")
    gesture_target_durations = _require_dict(
        config_snapshot, "gesture_target_durations"
    )
    gesture = _require_str(manifest, "gesture")

    capture_window_duration_s = _require_float(runtime, "capture_window_duration_s")
    countdown_duration_s = _require_float(runtime, "countdown_duration_s")
    marked_window_end_grace_s = _require_float(runtime, "marked_window_end_grace_s")
    end_mark_key = _require_str(runtime, "end_mark_key")
    target_window_duration_s = _require_float(gesture_target_durations, gesture)

    max_target_start_s = (
        capture_window_duration_s - target_window_duration_s - marked_window_end_grace_s
    )
    if max_target_start_s < 0:
        msg = "target_window_duration_s + grace exceeds capture_window_duration_s."
        raise ValueError(msg)

    target_start_s = SYSTEM_RANDOM.uniform(0.0, max_target_start_s)
    target_window = WindowRange(
        start_s=target_start_s,
        end_s=target_start_s + target_window_duration_s,
    )
    capture_window = WindowRange(
        start_s=0.0,
        end_s=capture_window_duration_s,
    )
    marked_window_deadline_s = target_window.end_s + marked_window_end_grace_s
    capture_start_delay_s = countdown_duration_s - target_window.start_s
    if capture_start_delay_s < 0:
        msg = "countdown_duration_s is too short for the randomized capture start."
        raise ValueError(msg)

    return AttemptPlan(
        countdown_duration_s=countdown_duration_s,
        capture_window=capture_window,
        target_window=target_window,
        marked_window_deadline_s=marked_window_deadline_s,
        capture_start_delay_s=capture_start_delay_s,
        end_mark_key=end_mark_key,
    )


def _capture_poll_timeout(original_timeout: float | None) -> float:
    """Choose a short poll timeout for responsive live capture prompts."""
    if original_timeout is None:
        return CAPTURE_POLL_TIMEOUT_SECONDS
    return min(original_timeout, CAPTURE_POLL_TIMEOUT_SECONDS)


def _emit_countdown_tick(
    *,
    now: float,
    go_at: float,
    last_countdown_value: int | None,
) -> int | None:
    """Render countdown ticks only when the visible second changes."""
    remaining_s = go_at - now
    if remaining_s <= 0:
        return last_countdown_value

    visible_value = math.ceil(remaining_s)
    if visible_value != last_countdown_value:
        _render_countdown_tick(visible_value)
    return visible_value


def _configure_radar(manifest: collection_session.JsonObject) -> None:
    """Send the configured cfg to the radar before starting the session."""
    config_id = _load_firmware_config_id(manifest)
    config_snapshot = _require_dict(manifest, "config_snapshot")
    serial_defaults = _require_dict(config_snapshot, "serial")

    config_path = mmwave_config.get_known_config(config_id).path.resolve()
    cli_baudrate = _require_int(serial_defaults, "cli_baudrate")
    cli_port = _require_str(manifest, "cli_port")

    console.print(f"state: configuring radar from {config_id} ({config_path})")
    session = send_config(
        cli_port=cli_port,
        cli_baudrate=cli_baudrate,
        config_path=config_path,
        stream_output=False,
    )
    validate_cli_session(session)


def _load_firmware_config_id(manifest: collection_session.JsonObject) -> str:
    """Load the runtime-selected firmware cfg id from the manifest contract."""
    return _require_str(manifest, "firmware_config_id")


def _require_dict(
    data: collection_session.JsonObject,
    key: str,
) -> collection_session.JsonObject:
    """Require one object field from a manifest mapping."""
    value = data.get(key)
    if isinstance(value, dict):
        return value

    msg = f"Field {key!r} must be an object."
    raise ValueError(msg)


def _require_str(data: collection_session.JsonObject, key: str) -> str:
    """Require one string field from a manifest mapping."""
    value = data.get(key)
    if isinstance(value, str) and value:
        return value

    msg = f"Field {key!r} must be a string."
    raise ValueError(msg)


def _require_int(data: collection_session.JsonObject, key: str) -> int:
    """Require one integer field from a manifest mapping."""
    value = data.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value

    msg = f"Field {key!r} must be an integer."
    raise ValueError(msg)


def _require_float(data: collection_session.JsonObject, key: str) -> float:
    """Require one numeric field from a manifest mapping."""
    value = data.get(key)
    if isinstance(value, int | float):
        return float(value)

    msg = f"Field {key!r} must be numeric."
    raise ValueError(msg)


@dataclass(slots=True)
class _MarkedWindowRecorder:
    """Best-effort live key recorder for marked_window capture."""

    capture_duration_s: float
    target_window: WindowRange
    end_mark_key: str
    end_s: float | None = None
    _stdin_fd: int | None = None
    _original_state: TerminalAttributes | None = None

    def __enter__(self) -> Self:
        """Switch stdin into cbreak mode when supported."""
        if msvcrt is not None:
            # On Windows, msvcrt handles non-blocking I/O directly.
            self._stdin_fd = sys.stdin.fileno() if sys.stdin.isatty() else None
            return self

        if termios is None or tty is None or not sys.stdin.isatty():
            return self

        try:
            stdin_fd = sys.stdin.fileno()
            original_state = termios.tcgetattr(stdin_fd)
            tty.setcbreak(stdin_fd)
        except OSError:
            self._stdin_fd = None
            self._original_state = None
            return self

        self._stdin_fd = stdin_fd
        self._original_state = original_state
        return self

    def __exit__(
        self,
        _exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> None:
        """Restore the original terminal mode."""
        if msvcrt is not None:
            return

        if termios is None:
            return

        stdin_fd = self._stdin_fd
        original_state = self._original_state
        if stdin_fd is None or original_state is None:
            return

        termios.tcsetattr(
            stdin_fd,
            termios.TCSADRAIN,
            original_state,
        )

    @property
    def window(self) -> WindowRange | None:
        """Return the completed window only when a valid end mark was recorded."""
        if self.end_s is None:
            return None
        if self.end_s <= self.target_window.start_s:
            return None
        return WindowRange(
            start_s=self.target_window.start_s,
            end_s=min(self.capture_duration_s, self.end_s),
        )

    def poll(self, *, elapsed_seconds: float) -> None:
        """Record the end mark once the operator presses the configured key."""
        if not self._ready_for_poll(elapsed_seconds):
            return
        key = _read_non_blocking_key()
        if key is None or not _matches_end_mark_key(key, self.end_mark_key):
            return

        self.end_s = elapsed_seconds
        console.print(f"mark: end @ {elapsed_seconds:.2f}s")

    def _ready_for_poll(self, elapsed_seconds: float) -> bool:
        """Return whether one poll call may still record an end mark."""
        return (
            self._stdin_fd is not None
            and self.end_s is None
            and elapsed_seconds >= self.target_window.start_s
        )


def _matches_end_mark_key(key: str, configured_key: str) -> bool:
    """Return whether one terminal key matches the configured end marker."""
    return _normalize_key_name(key) == _normalize_key_name(configured_key)


def _normalize_key_name(value: str) -> str:
    """Normalize literal keys and named keys like `space`."""
    normalized = value.strip().lower()
    if value == " " or normalized == "space":
        return "space"
    return normalized


def _read_non_blocking_key() -> str | None:
    """Return one keypress when available without blocking the capture loop."""
    if msvcrt is not None:
        return _read_windows_key()
    return _read_posix_key()


def _read_windows_key() -> str | None:
    """Return one keypress from msvcrt when available."""
    if not _msvcrt_key_available():
        return None

    raw_key = _msvcrt_getch()
    if raw_key is None:
        return None

    try:
        return raw_key.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _msvcrt_key_available() -> bool:
    """Return whether msvcrt reports a pending keypress."""
    if msvcrt is None:
        return False
    kbhit = getattr(msvcrt, "kbhit", None)
    if not callable(kbhit):
        return False
    return cast("Callable[[], bool]", kbhit)()


def _msvcrt_getch() -> bytes | None:
    """Return one raw keypress from msvcrt when supported."""
    if msvcrt is None:
        return None
    getch = getattr(msvcrt, "getch", None)
    if not callable(getch):
        return None
    return cast("Callable[[], bytes]", getch)()


def _read_posix_key() -> str | None:
    """Return one keypress from stdin when POSIX non-blocking I/O is ready."""
    ready, _, _ = select.select([sys.stdin], [], [], 0.0)
    if not ready:
        return None

    try:
        return sys.stdin.read(1)
    except OSError:
        return None
