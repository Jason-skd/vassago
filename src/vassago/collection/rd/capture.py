"""Live session execution for RD collection workflows."""

from __future__ import annotations

import math
import random
import select
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Self

import serial
from rich.console import Console

from vassago.collection.rd import quick_qc
from vassago.collection.rd import session as collection_session
from vassago.collection.rd import ui as collection_ui
from vassago.collection.rd.config import WindowRange
from vassago.collection.rd.paths import resolve_repo_path
from vassago.firmware.mmwave import config as mmwave_config
from vassago.firmware.mmwave.protocol import MmwavePacketParser
from vassago.firmware.mmwave.protocol import SmokeTestSummary
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

type TerminalAttributes = (
    list[int | list[bytes | int]] | list[int | list[bytes]] | list[int | list[int]]
)

console = Console()
CAPTURE_LOOP_SLEEP_SECONDS = 0.01
CAPTURE_POLL_TIMEOUT_SECONDS = 0.05
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


def run_session(
    manifest_path: Path,
    *,
    read_size: int = DEFAULT_READ_SIZE,
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
            batch_size = _require_int(manifest, "batch_size")
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

            capture_result = capture_take(
                connection,
                attempt_plan=attempt_plan,
                read_size=read_size,
            )
            summary = summarize_raw_capture(capture_result.raw_capture)
            collection_ui.render_capture_summary(
                console,
                summary=summary,
                capture_window=capture_result.capture_window,
                target_window=capture_result.target_window,
                marked_window=capture_result.marked_window,
            )

            qc_decision = quick_qc.evaluate_capture(
                summary=summary,
                target_window=capture_result.target_window,
                marked_window=capture_result.marked_window,
                marked_window_end_grace_s=(
                    attempt_plan.marked_window_deadline_s
                    - attempt_plan.target_window.end_s
                ),
            )
            collection_ui.render_quick_qc(console, decision=qc_decision)
            if not qc_decision.accepted:
                decision = collection_ui.prompt_rejected_take_action(take_id=take_id)
                if decision == collection_ui.TAKE_DECISION_QUIT:
                    return
                continue

            decision = collection_ui.prompt_take_decision(take_id=take_id)
            if decision == collection_ui.TAKE_DECISION_RETRY:
                continue
            if decision == collection_ui.TAKE_DECISION_QUIT:
                return

            raw_uart_path = collection_session.build_take_output_path(
                manifest_path=manifest_path,
                take=take,
            )
            raw_uart_path.write_bytes(capture_result.raw_capture)
            collection_session.accept_take(
                manifest=manifest,
                take=take,
                raw_uart_path=raw_uart_path,
                capture_window=capture_result.capture_window,
                target_window=capture_result.target_window,
                marked_window=capture_result.marked_window,
            )
            collection_session.write_manifest(
                manifest_path=manifest_path,
                manifest=manifest,
            )


def capture_take(
    connection: serial.Serial,
    *,
    attempt_plan: AttemptPlan,
    read_size: int,
) -> TakeCaptureResult:
    """Capture one attempt with fixed countdown, GO, and hidden capture start."""
    console.print("state: countdown")
    console.print(
        f"control: wait for GO, then press {attempt_plan.end_mark_key} to mark end"
    )

    timeline_start = time.perf_counter()
    go_at = timeline_start + attempt_plan.countdown_duration_s
    capture_start_at = timeline_start + attempt_plan.capture_start_delay_s
    capture_end_at = capture_start_at + (
        attempt_plan.capture_window.end_s - attempt_plan.capture_window.start_s
    )
    target_end_at = capture_start_at + attempt_plan.target_window.end_s
    raw_capture = bytearray()

    last_countdown_value: int | None = None
    capture_started = False
    go_announced = False
    target_end_announced = False

    original_timeout = connection.timeout
    connection.timeout = _capture_poll_timeout(original_timeout)
    try:
        with _MarkedWindowRecorder(
            capture_duration_s=attempt_plan.capture_window.end_s,
            target_window=attempt_plan.target_window,
            end_mark_key=attempt_plan.end_mark_key,
        ) as marker:
            while True:
                now = time.perf_counter()
                if not go_announced:
                    last_countdown_value = _emit_countdown_tick(
                        now=now,
                        go_at=go_at,
                        last_countdown_value=last_countdown_value,
                    )

                if not capture_started and now >= capture_start_at:
                    capture_started = True
                    connection.reset_input_buffer()

                if not go_announced and now >= go_at:
                    go_announced = True
                    console.print("GO")

                if capture_started:
                    capture_elapsed_s = min(
                        attempt_plan.capture_window.end_s,
                        now - capture_start_at,
                    )
                    marker.poll(elapsed_seconds=capture_elapsed_s)

                    if not target_end_announced and now >= target_end_at:
                        target_end_announced = True
                        console.print("target_window ended")

                    if now >= capture_end_at:
                        break

                    chunk = connection.read(read_size)
                    if chunk:
                        raw_capture.extend(chunk)
                    marker.poll(
                        elapsed_seconds=min(
                            attempt_plan.capture_window.end_s,
                            time.perf_counter() - capture_start_at,
                        ),
                    )
                    continue

                time.sleep(CAPTURE_LOOP_SLEEP_SECONDS)

            marker.poll(elapsed_seconds=attempt_plan.capture_window.end_s)
            marked_window = marker.window
    finally:
        connection.timeout = original_timeout

    console.print("capture_window ended")
    return TakeCaptureResult(
        raw_capture=bytes(raw_capture)
        + read_available_bytes(connection, read_size=read_size),
        capture_window=attempt_plan.capture_window,
        target_window=attempt_plan.target_window,
        marked_window=marked_window,
    )


def summarize_raw_capture(raw_capture: bytes) -> SmokeTestSummary:
    """Parse one captured UART window into the same summary used by smoke-test."""
    parser = MmwavePacketParser()
    packets = parser.feed(raw_capture)
    return summarize_packets(
        packets=packets,
        bytes_read=len(raw_capture),
        invalid_packet_count=parser.invalid_packet_count,
    )


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
        console.print(f"countdown: {visible_value}")
    return visible_value


def _configure_radar(manifest: collection_session.JsonObject) -> None:
    """Send the configured cfg to the radar before starting the session."""
    config_snapshot = _require_dict(manifest, "config_snapshot")
    firmware = _require_dict(config_snapshot, "firmware")
    serial_defaults = _require_dict(config_snapshot, "serial")

    config_id = _require_str(firmware, "config_id")
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
        if self._stdin_fd is None:
            return
        if self.end_s is not None:
            return
        if elapsed_seconds < self.target_window.start_s:
            return

        ready, _, _ = select.select([sys.stdin], [], [], 0.0)
        if not ready:
            return

        try:
            key = sys.stdin.read(1)
        except OSError:
            return

        if not _matches_end_mark_key(key, self.end_mark_key):
            return

        self.end_s = elapsed_seconds
        console.print(f"mark: end @ {elapsed_seconds:.2f}s")


def _matches_end_mark_key(key: str, configured_key: str) -> bool:
    """Return whether one terminal key matches the configured end marker."""
    return _normalize_key_name(key) == _normalize_key_name(configured_key)


def _normalize_key_name(value: str) -> str:
    """Normalize literal keys and named keys like `space`."""
    normalized = value.strip().lower()
    if value == " " or normalized == "space":
        return "space"
    return normalized
