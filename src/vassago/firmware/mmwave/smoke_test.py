"""Serial-backed probe and smoke-test workflows for TI-style mmWave boards."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import serial

from vassago.firmware.mmwave.ports import SerialPortInfo
from vassago.firmware.mmwave.ports import list_candidate_mmwave_ports
from vassago.firmware.mmwave.ports import list_serial_ports
from vassago.firmware.mmwave.protocol import MmwavePacket
from vassago.firmware.mmwave.protocol import MmwavePacketParser
from vassago.firmware.mmwave.protocol import SmokeTestSummary
from vassago.firmware.mmwave.protocol import summarize_packets

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Sequence
    from pathlib import Path

DEFAULT_CLI_BAUDRATE = 115_200
DEFAULT_DATA_BAUDRATE = 921_600
DEFAULT_DURATION_SECONDS = 5.0
DEFAULT_PROBE_DURATION_SECONDS = 1.5
DEFAULT_MIN_PACKETS = 3
DEFAULT_READ_SIZE = 4096
DEFAULT_READ_TIMEOUT_SECONDS = 0.2
DEFAULT_CONFIG_LINE_DELAY_SECONDS = 0.05
DEFAULT_CLI_COMMAND_TIMEOUT_SECONDS = 1.0
DEFAULT_CLI_READY_TIMEOUT_SECONDS = 4.0
DEFAULT_CLI_READY_RETRIES = 3
FIRST_HEXDUMP_MIN_BYTES = 30


@dataclass(slots=True, frozen=True)
class CliCommandResult:
    """One CLI command plus the observed device responses."""

    command: str
    responses: tuple[str, ...]

    @property
    def failed(self) -> bool:
        """Return whether the CLI reported an error-like response."""
        failure_markers = (
            "exception:",
            "error",
            "failed",
            "not recognized as a cli command",
        )
        return any(
            marker in response.lower()
            for response in self.responses
            for marker in failure_markers
        )


@dataclass(slots=True, frozen=True)
class CliSessionResult:
    """Result of sending a cfg file over the CLI port."""

    startup_responses: tuple[str, ...]
    startup_prompt_seen: bool
    commands: tuple[CliCommandResult, ...]

    @property
    def failed_command(self) -> CliCommandResult | None:
        """Return the first failed command, if any."""
        for command_result in self.commands:
            if command_result.failed:
                return command_result
        return None


@dataclass(slots=True, frozen=True)
class PortProbeResult:
    """Best-effort probe result for one visible serial port."""

    port: str
    description: str
    cli_prompt_seen: bool
    cli_response_lines: tuple[str, ...]
    data_bytes_read: int
    valid_packet_count: int
    invalid_packet_count: int


def load_config_lines(config_path: Path) -> list[str]:
    """Load non-empty cfg lines, skipping comment-only lines."""
    lines: list[str] = []
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("%", "#")):
            continue
        lines.append(line)
    return lines


def send_config(
    *,
    cli_port: str,
    cli_baudrate: int,
    config_path: Path,
    stream_output: bool = False,
) -> CliSessionResult:
    """Send a cfg file to the CLI port and collect per-command responses."""
    commands = load_config_lines(config_path)
    command_results: list[CliCommandResult] = []

    with serial.Serial(
        port=cli_port,
        baudrate=cli_baudrate,
        timeout=DEFAULT_READ_TIMEOUT_SECONDS,
    ) as connection:
        time.sleep(DEFAULT_READ_TIMEOUT_SECONDS)
        connection.reset_input_buffer()
        startup_responses, startup_prompt_seen = _wait_for_cli_ready(connection)

        if stream_output and startup_responses:
            for response in startup_responses:
                print(f"cli: {response}")

        if not startup_prompt_seen:
            return CliSessionResult(
                startup_responses=tuple(startup_responses),
                startup_prompt_seen=False,
                commands=(),
            )

        for command in commands:
            if stream_output:
                print(f"cli> {command}")
            connection.write(f"{command}\n".encode())
            connection.flush()
            responses = _read_cli_until_prompt(connection)
            if stream_output:
                if responses:
                    for response in responses:
                        print(f"cli: {response}")
                else:
                    print("cli: <no response before timeout>")
            command_results.append(
                CliCommandResult(command=command, responses=tuple(responses)),
            )
            if not responses:
                break

    return CliSessionResult(
        startup_responses=tuple(startup_responses),
        startup_prompt_seen=True,
        commands=tuple(command_results),
    )


def run_smoke_test(
    *,
    data_port: str,
    data_baudrate: int,
    duration_seconds: float,
    read_size: int,
    verbose: bool,
) -> SmokeTestSummary:
    """Read the data port for a fixed interval and summarize valid packets."""
    parser = MmwavePacketParser()
    packets: list[MmwavePacket] = []
    bytes_read = 0
    deadline = time.perf_counter() + duration_seconds

    with serial.Serial(
        port=data_port,
        baudrate=data_baudrate,
        timeout=DEFAULT_READ_TIMEOUT_SECONDS,
    ) as connection:
        connection.reset_input_buffer()

        while time.perf_counter() < deadline:
            chunk = connection.read(read_size)
            if not chunk:
                continue

            if bytes_read == 0 and len(chunk) > FIRST_HEXDUMP_MIN_BYTES:
                print("\n" + "=" * 50)
                print("First data chunk (hex dump)")
                print(chunk[:128].hex())
                print("=" * 50 + "\n")

            bytes_read += len(chunk)
            new_packets = parser.feed(chunk)
            packets.extend(new_packets)

            if verbose:
                for packet in new_packets:
                    print(f"frame={packet.frame_number} tlvs={packet.num_tlvs}")

    return summarize_packets(
        packets=packets,
        bytes_read=bytes_read,
        invalid_packet_count=parser.invalid_packet_count,
    )


def probe_port(
    *,
    port: SerialPortInfo,
    cli_baudrate: int,
    data_baudrate: int,
    probe_duration_seconds: float,
    read_size: int,
) -> PortProbeResult:
    """Probe one port for CLI prompt visibility and data activity."""
    cli_prompt_seen = False
    cli_response_lines: tuple[str, ...] = ()

    try:
        with serial.Serial(
            port=port.device,
            baudrate=cli_baudrate,
            timeout=DEFAULT_READ_TIMEOUT_SECONDS,
        ) as connection:
            time.sleep(DEFAULT_READ_TIMEOUT_SECONDS)
            connection.reset_input_buffer()
            startup_lines, cli_prompt_seen = _wait_for_cli_ready(connection)
            cli_response_lines = tuple(startup_lines)
    except serial.SerialException:
        cli_prompt_seen = False
        cli_response_lines = ()

    try:
        summary = run_smoke_test(
            data_port=port.device,
            data_baudrate=data_baudrate,
            duration_seconds=probe_duration_seconds,
            read_size=read_size,
            verbose=False,
        )
    except serial.SerialException:
        summary = SmokeTestSummary(0, 0, 0, None, None, 0, 0, {})

    return PortProbeResult(
        port=port.device,
        description=port.description,
        cli_prompt_seen=cli_prompt_seen,
        cli_response_lines=cli_response_lines,
        data_bytes_read=summary.bytes_read,
        valid_packet_count=summary.valid_packet_count,
        invalid_packet_count=summary.invalid_packet_count,
    )


def collect_probe_results(
    *,
    cli_baudrate: int,
    data_baudrate: int,
    probe_duration_seconds: float,
    read_size: int,
    candidate_ports: Sequence[SerialPortInfo] | None = None,
) -> list[PortProbeResult]:
    """Probe likely candidate ports and return one result per port."""
    candidates = (
        list(candidate_ports)
        if candidate_ports is not None
        else list_candidate_mmwave_ports(list_serial_ports())
    )
    return [
        probe_port(
            port=port,
            cli_baudrate=cli_baudrate,
            data_baudrate=data_baudrate,
            probe_duration_seconds=probe_duration_seconds,
            read_size=read_size,
        )
        for port in candidates
    ]


def infer_port_roles(
    probe_results: Iterable[PortProbeResult],
) -> tuple[str | None, str | None]:
    """Infer likely CLI and Data ports from probe observations."""
    results = list(probe_results)
    cli_candidates = [result.port for result in results if result.cli_prompt_seen]
    cli_port = cli_candidates[0] if len(cli_candidates) == 1 else None

    data_candidates = [
        result.port
        for result in sorted(
            results,
            key=lambda result: (
                result.valid_packet_count,
                result.data_bytes_read,
            ),
            reverse=True,
        )
        if result.port != cli_port and result.data_bytes_read > 0
    ]

    if data_candidates:
        return cli_port, data_candidates[0]

    if cli_port is not None:
        remaining_ports = [result.port for result in results if result.port != cli_port]
        if len(remaining_ports) == 1:
            return cli_port, remaining_ports[0]

    return cli_port, None


def validate_cli_session(session: CliSessionResult) -> None:
    """Raise a readable error if radar configuration did not complete."""
    if not session.startup_prompt_seen:
        msg = "CLI did not become ready before config."
        raise RuntimeError(msg)

    failed_command = session.failed_command
    if failed_command is not None:
        msg = f"Radar config failed at command: {failed_command.command}"
        raise RuntimeError(msg)

    stalled_command = next(
        (
            command_result.command
            for command_result in session.commands
            if not command_result.responses
        ),
        None,
    )
    if stalled_command is not None:
        msg = f"Radar config timed out at command: {stalled_command}"
        raise RuntimeError(msg)


def build_recovery_hint(*, failed_command: str | None = None) -> str:
    """Return the next operator step for common transient failures."""
    if failed_command == "sensorStart":
        return (
            "If this cfg worked earlier, power-cycle the board, re-run the "
            "baseline cfg, then retry this cfg."
        )

    if failed_command is not None:
        return (
            "This cfg appears incompatible with the current firmware. Remove or "
            "replace the unsupported command, or switch back to the baseline cfg "
            "before retrying."
        )

    return (
        "If probe-ports also shows no CLI prompt and no data activity, "
        "power-cycle the board and rerun probe-ports before retrying."
    )


def _read_cli_until_prompt(connection: serial.Serial) -> list[str]:
    """Read CLI UART text until the prompt reappears or timeout elapses."""
    deadline = time.perf_counter() + DEFAULT_CLI_COMMAND_TIMEOUT_SECONDS
    decoded_text = ""

    while time.perf_counter() < deadline:
        raw_chunk = connection.read_all()
        if raw_chunk:
            decoded_text += raw_chunk.decode("utf-8", errors="replace")
            if "mmwDemo:/>" in decoded_text:
                break
        else:
            time.sleep(DEFAULT_CONFIG_LINE_DELAY_SECONDS)

    return [line for line in decoded_text.splitlines() if line.strip()]


def _wait_for_cli_ready(connection: serial.Serial) -> tuple[list[str], bool]:
    """Wait until the CLI prompt is visible, nudging it with blank lines."""
    collected_lines: list[str] = []

    for attempt in range(DEFAULT_CLI_READY_RETRIES + 1):
        lines = _read_cli_until_prompt_with_timeout(
            connection,
            timeout_seconds=DEFAULT_CLI_READY_TIMEOUT_SECONDS,
        )
        if lines:
            collected_lines.extend(lines)
            if any("mmwDemo:/>" in line for line in lines):
                return collected_lines, True

        if attempt < DEFAULT_CLI_READY_RETRIES:
            connection.write(b"\n")
            connection.flush()

    return collected_lines, False


def _read_cli_until_prompt_with_timeout(
    connection: serial.Serial,
    *,
    timeout_seconds: float,
) -> list[str]:
    """Read CLI UART text until the prompt reappears or timeout elapses."""
    deadline = time.perf_counter() + timeout_seconds
    decoded_text = ""

    while time.perf_counter() < deadline:
        raw_chunk = connection.read_all()
        if raw_chunk:
            decoded_text += raw_chunk.decode("utf-8", errors="replace")
            if "mmwDemo:/>" in decoded_text:
                break
        else:
            time.sleep(DEFAULT_CONFIG_LINE_DELAY_SECONDS)

    return [line for line in decoded_text.splitlines() if line.strip()]
