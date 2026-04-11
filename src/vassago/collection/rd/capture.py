"""Live session execution for RD collection workflows."""

from __future__ import annotations

import select
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Self

import serial
from rich.console import Console

from vassago.collection.rd import session as collection_session
from vassago.collection.rd import ui as collection_ui
from vassago.collection.rd.config import WindowRange
from vassago.collection.rd.paths import resolve_repo_path
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


@dataclass(slots=True, frozen=True)
class TakeCaptureResult:
    """Raw UART bytes plus the operator-marked window for one take."""

    raw_capture: bytes
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
    console.print(
        f"Collection session stopped: {session_id} ({final_status})",
    )
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

            target_window = _window_from_dict(take.get("target_window"))
            take_index = _require_int(take, "take_index")
            take_id = _require_str(take, "take_id")
            batch_size = _require_int(manifest, "batch_size")
            collection_ui.render_take_state(
                console,
                take_id=take_id,
                take_index=take_index,
                batch_size=batch_size,
                target_window=target_window,
                accepted_take_count=collection_session.count_accepted_takes(manifest),
                remaining_take_count=collection_session.count_remaining_takes(manifest),
            )

            action = collection_ui.prompt_take_action(take_id=take_id)
            if action == collection_ui.TAKE_ACTION_QUIT:
                return

            capture_result = capture_take(
                connection,
                duration_seconds=_capture_duration_seconds(take),
                read_size=read_size,
            )
            summary = summarize_raw_capture(capture_result.raw_capture)
            collection_ui.render_capture_summary(
                console,
                summary=summary,
                marked_window=capture_result.marked_window,
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
            raw_uart_path.write_bytes(capture_result.raw_capture)
            collection_session.accept_take(
                manifest=manifest,
                take=take,
                raw_uart_path=raw_uart_path,
                marked_window=capture_result.marked_window,
            )
            collection_session.write_manifest(
                manifest_path=manifest_path,
                manifest=manifest,
            )


def capture_take(
    connection: serial.Serial,
    *,
    duration_seconds: float,
    read_size: int,
) -> TakeCaptureResult:
    """Capture one fixed-duration data window while polling for live marks."""
    console.print("state: capturing")
    console.print("control: press m at gesture start, then m again at gesture end")
    connection.reset_input_buffer()
    with _MarkedWindowRecorder(duration_seconds=duration_seconds) as marker:
        raw_capture = read_data_window(
            connection,
            duration_seconds=duration_seconds,
            read_size=read_size,
            marker=marker,
        )
    raw_capture += read_available_bytes(connection, read_size=read_size)
    return TakeCaptureResult(
        raw_capture=raw_capture,
        marked_window=marker.window,
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


def read_data_window(
    connection: serial.Serial,
    *,
    duration_seconds: float,
    read_size: int,
    marker: _MarkedWindowRecorder,
) -> bytes:
    """Read raw bytes from the data UART for a fixed duration."""
    buffer = bytearray()
    start_time = time.perf_counter()
    deadline = start_time + duration_seconds

    while True:
        now = time.perf_counter()
        if now >= deadline:
            return bytes(buffer)

        chunk = connection.read(read_size)
        if chunk:
            buffer.extend(chunk)

        marker.poll(elapsed_seconds=now - start_time)


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


def _configure_radar(manifest: collection_session.JsonObject) -> None:
    """Send the configured cfg to the radar before starting the session."""
    config_snapshot = _require_dict(manifest, "config_snapshot")
    firmware = _require_dict(config_snapshot, "firmware")
    serial_defaults = _require_dict(config_snapshot, "serial")

    config_path = resolve_repo_path(_require_str(firmware, "config_path"))
    cli_baudrate = _require_int(serial_defaults, "cli_baudrate")
    cli_port = _require_str(manifest, "cli_port")

    console.print(f"state: configuring radar from {config_path}")
    session = send_config(
        cli_port=cli_port,
        cli_baudrate=cli_baudrate,
        config_path=config_path,
        stream_output=False,
    )
    validate_cli_session(session)


def _capture_duration_seconds(take: collection_session.JsonObject) -> float:
    """Extract the fixed capture duration from one take record."""
    capture_window = _window_from_dict(take.get("capture_window"))
    return capture_window.end_s - capture_window.start_s


def _window_from_dict(value: object) -> WindowRange:
    """Parse one manifest window mapping back into a typed object."""
    if not isinstance(value, dict):
        msg = "Expected a window object."
        raise TypeError(msg)

    start_s = value.get("start_s")
    end_s = value.get("end_s")
    if not isinstance(start_s, int | float) or not isinstance(end_s, int | float):
        msg = "Window start_s and end_s must be numeric."
        raise TypeError(msg)
    return WindowRange(start_s=float(start_s), end_s=float(end_s))


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


@dataclass(slots=True)
class _MarkedWindowRecorder:
    """Best-effort live key recorder for marked_window capture."""

    duration_seconds: float
    start_s: float | None = None
    end_s: float | None = None
    _stdin_fd: int | None = None
    _original_state: TerminalAttributes | None = None

    def __enter__(self) -> Self:
        """Switch stdin into cbreak mode when supported."""
        try:
            if termios is None or tty is None or not sys.stdin.isatty():
                return self

            stdin_fd = sys.stdin.fileno()
            original_state = termios.tcgetattr(stdin_fd)
            tty.setcbreak(stdin_fd)
            self._stdin_fd = stdin_fd
            self._original_state = original_state
        except ImportError, OSError:
            self._stdin_fd = None
            self._original_state = None

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
        """Return the completed window only when two valid marks were recorded."""
        if self.start_s is None or self.end_s is None:
            return None
        if self.start_s >= self.end_s:
            return None
        return WindowRange(
            start_s=max(0.0, self.start_s),
            end_s=min(self.duration_seconds, self.end_s),
        )

    def poll(self, *, elapsed_seconds: float) -> None:
        """Record start/end marks when the operator presses m."""
        if self._stdin_fd is None:
            return

        ready, _, _ = select.select([sys.stdin], [], [], 0.0)
        if not ready:
            return

        try:
            key = sys.stdin.read(1).lower()
        except OSError:
            return

        if key != "m":
            return

        if self.start_s is None:
            self.start_s = elapsed_seconds
            console.print(f"mark: start @ {elapsed_seconds:.2f}s")
            return

        if self.end_s is None:
            self.end_s = elapsed_seconds
            console.print(f"mark: end @ {elapsed_seconds:.2f}s")
