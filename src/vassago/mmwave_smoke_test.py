"""Minimal smoke test for TI-style mmWave UART firmware output.

This module is intentionally narrow in scope:

- optionally send a `.cfg` file to the CLI port
- listen on the data port
- validate that the firmware emits well-formed UART packets

It does not reconstruct RD data yet. The goal is only to answer:
"is the firmware alive and speaking the expected binary protocol?"
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import serial
from serial.tools import list_ports

if TYPE_CHECKING:
    from collections.abc import Iterable

MAGIC_WORD = b"\x02\x01\x04\x03\x06\x05\x08\x07"
MAGIC_WORD_SIZE = len(MAGIC_WORD)
HEADER_BODY_FORMAT = "<8I"
HEADER_BODY_SIZE = struct.calcsize(HEADER_BODY_FORMAT)
HEADER_SIZE = MAGIC_WORD_SIZE + HEADER_BODY_SIZE
TLV_HEADER_FORMAT = "<II"
TLV_HEADER_SIZE = struct.calcsize(TLV_HEADER_FORMAT)

DEFAULT_CLI_BAUDRATE = 115_200
DEFAULT_DATA_BAUDRATE = 921_600
DEFAULT_DURATION_SECONDS = 5.0
DEFAULT_MIN_PACKETS = 3
DEFAULT_READ_SIZE = 4096
DEFAULT_READ_TIMEOUT_SECONDS = 0.2
DEFAULT_CONFIG_LINE_DELAY_SECONDS = 0.05
DEFAULT_CLI_COMMAND_TIMEOUT_SECONDS = 1.0
DEFAULT_CLI_READY_TIMEOUT_SECONDS = 4.0
DEFAULT_CLI_READY_RETRIES = 3
MAX_PACKET_SIZE_BYTES = 1_048_576


@dataclass(slots=True, frozen=True)
class MmwavePacket:
    """Parsed mmWave UART packet header plus TLV type summary."""

    version: int
    total_packet_length: int
    platform: int
    frame_number: int
    time_cpu_cycles: int
    num_detected_objects: int
    num_tlvs: int
    sub_frame_number: int
    tlv_types: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class SmokeTestSummary:
    """Aggregated smoke test result."""

    bytes_read: int
    valid_packet_count: int
    invalid_packet_count: int
    first_frame_number: int | None
    last_frame_number: int | None
    frame_gap_count: int
    non_monotonic_frame_count: int
    tlv_type_counts: dict[int, int]

    def passed(self, minimum_packet_count: int) -> bool:
        """Return whether the smoke test collected enough valid packets."""
        return self.valid_packet_count >= minimum_packet_count


@dataclass(slots=True, frozen=True)
class CliCommandResult:
    """CLI command plus the device responses observed after sending it."""

    command: str
    responses: tuple[str, ...]

    @property
    def failed(self) -> bool:
        """Return whether the CLI reported an exception or error."""
        failure_markers = ("exception:", "error", "failed")
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
        """Return the first failed command if any."""
        for command_result in self.commands:
            if command_result.failed:
                return command_result
        return None


class MmwavePacketParser:
    """Streaming parser for TI mmWave-style UART packets."""

    def __init__(self) -> None:
        """Initialize the parser with an empty byte buffer."""
        self._buffer = bytearray()
        self.invalid_packet_count = 0

    def feed(self, data: bytes) -> list[MmwavePacket]:
        """Consume bytes and return any complete packets found."""
        self._buffer.extend(data)
        packets: list[MmwavePacket] = []

        while True:
            if len(self._buffer) < MAGIC_WORD_SIZE:
                return packets

            packet_start = self._buffer.find(MAGIC_WORD)
            if packet_start < 0:
                self._buffer = self._buffer[-(MAGIC_WORD_SIZE - 1) :]
                return packets

            if packet_start > 0:
                del self._buffer[:packet_start]

            if len(self._buffer) < HEADER_SIZE:
                return packets

            header = self._parse_header(self._buffer)
            if header is None:
                self.invalid_packet_count += 1
                del self._buffer[0]
                continue

            if len(self._buffer) < header.total_packet_length:
                return packets

            packet_bytes = bytes(self._buffer[: header.total_packet_length])
            del self._buffer[: header.total_packet_length]

            tlv_types = self._parse_tlv_types(
                packet_bytes=packet_bytes,
                total_packet_length=header.total_packet_length,
                num_tlvs=header.num_tlvs,
            )
            if tlv_types is None:
                self.invalid_packet_count += 1
                continue

            packets.append(
                MmwavePacket(
                    version=header.version,
                    total_packet_length=header.total_packet_length,
                    platform=header.platform,
                    frame_number=header.frame_number,
                    time_cpu_cycles=header.time_cpu_cycles,
                    num_detected_objects=header.num_detected_objects,
                    num_tlvs=header.num_tlvs,
                    sub_frame_number=header.sub_frame_number,
                    tlv_types=tlv_types,
                ),
            )

    @staticmethod
    def _parse_header(buffer: bytearray) -> MmwavePacket | None:
        """Parse the fixed-size packet header from the current buffer."""
        (
            version,
            total_packet_length,
            platform,
            frame_number,
            time_cpu_cycles,
            num_detected_objects,
            num_tlvs,
            sub_frame_number,
        ) = struct.unpack_from(HEADER_BODY_FORMAT, buffer, MAGIC_WORD_SIZE)

        if total_packet_length < HEADER_SIZE:
            return None
        if total_packet_length > MAX_PACKET_SIZE_BYTES:
            return None

        return MmwavePacket(
            version=version,
            total_packet_length=total_packet_length,
            platform=platform,
            frame_number=frame_number,
            time_cpu_cycles=time_cpu_cycles,
            num_detected_objects=num_detected_objects,
            num_tlvs=num_tlvs,
            sub_frame_number=sub_frame_number,
            tlv_types=(),
        )

    @staticmethod
    def _parse_tlv_types(
        *,
        packet_bytes: bytes,
        total_packet_length: int,
        num_tlvs: int,
    ) -> tuple[int, ...] | None:
        """Parse TLV headers and return the TLV type list for the packet."""
        offset = HEADER_SIZE
        tlv_types: list[int] = []

        for _ in range(num_tlvs):
            if offset + TLV_HEADER_SIZE > total_packet_length:
                break

            # 提取类型和“纯净重”(Payload Length)
            tlv_type, tlv_payload_length = struct.unpack_from(
                TLV_HEADER_FORMAT,
                packet_bytes,
                offset,
            )
            
            # 核心修复：真实跨度 = 皮重 (8) + 净重 (Payload)
            tlv_total_size = TLV_HEADER_SIZE + tlv_payload_length
            
            if offset + tlv_total_size > total_packet_length:
                break

            tlv_types.append(tlv_type)
            
            # 按真实跨度向后移动指针
            offset += tlv_total_size

        return tuple(tlv_types)

def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line interface."""
    parser = argparse.ArgumentParser(
        description=(
            "Minimal smoke test for mmWave firmware. "
            "Optionally sends a cfg file, then verifies that the data port "
            "emits valid TI-style UART packets."
        ),
    )
    parser.add_argument(
        "--data-port",
        help="Data UART port, for example /dev/cu.usbmodem1101.",
    )
    parser.add_argument(
        "--data-baudrate",
        type=int,
        default=DEFAULT_DATA_BAUDRATE,
        help=f"Data UART baudrate. Default: {DEFAULT_DATA_BAUDRATE}.",
    )
    parser.add_argument(
        "--cli-port",
        help="Optional CLI UART port for sending a cfg file.",
    )
    parser.add_argument(
        "--cli-baudrate",
        type=int,
        default=DEFAULT_CLI_BAUDRATE,
        help=f"CLI UART baudrate. Default: {DEFAULT_CLI_BAUDRATE}.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Optional path to a cfg file sent through the CLI port.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION_SECONDS,
        help=(
            "How long to read the data port, in seconds. "
            f"Default: {DEFAULT_DURATION_SECONDS}."
        ),
    )
    parser.add_argument(
        "--min-packets",
        type=int,
        default=DEFAULT_MIN_PACKETS,
        help=f"Minimum valid packets required to pass. Default: {DEFAULT_MIN_PACKETS}.",
    )
    parser.add_argument(
        "--read-size",
        type=int,
        default=DEFAULT_READ_SIZE,
        help=f"Bytes requested per serial read. Default: {DEFAULT_READ_SIZE}.",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="List serial ports visible to the host and exit.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each valid frame number while reading.",
    )
    return parser


def list_serial_ports() -> list[str]:
    """Return human-readable descriptions for visible serial ports."""
    port_descriptions: list[str] = []
    for port in list_ports.comports():
        description = port.description or "unknown"
        port_descriptions.append(f"{port.device} - {description}")
    return port_descriptions


def load_config_lines(config_path: Path) -> list[str]:
    """Load non-empty command lines from a mmWave cfg file."""
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


def _decode_cli_response(raw_response: bytes) -> list[str]:
    """Decode CLI UART text in a loss-tolerant way."""
    decoded = raw_response.decode("utf-8", errors="replace")
    return [line for line in decoded.splitlines() if line.strip()]


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

            # --- 新增的血液化验代码 ---
            if bytes_read == 0 and len(chunk) > 30:
                print("\n" + "="*50)
                print("🚨 抓取到第一帧底层二进制流 (HEX DUMP) 🚨")
                print(chunk[:128].hex())
                print("="*50 + "\n")
            # --------------------------

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


def summarize_packets(
    *,
    packets: Iterable[MmwavePacket],
    bytes_read: int,
    invalid_packet_count: int,
) -> SmokeTestSummary:
    """Aggregate high-level counters from parsed packets."""
    packet_list = list(packets)
    tlv_type_counts: Counter[int] = Counter()
    frame_gap_count = 0
    non_monotonic_frame_count = 0

    previous_frame_number: int | None = None
    for packet in packet_list:
        tlv_type_counts.update(packet.tlv_types)

        if previous_frame_number is not None:
            if packet.frame_number > previous_frame_number + 1:
                frame_gap_count += packet.frame_number - previous_frame_number - 1
            elif packet.frame_number <= previous_frame_number:
                non_monotonic_frame_count += 1

        previous_frame_number = packet.frame_number

    first_frame_number = packet_list[0].frame_number if packet_list else None
    last_frame_number = packet_list[-1].frame_number if packet_list else None

    return SmokeTestSummary(
        bytes_read=bytes_read,
        valid_packet_count=len(packet_list),
        invalid_packet_count=invalid_packet_count,
        first_frame_number=first_frame_number,
        last_frame_number=last_frame_number,
        frame_gap_count=frame_gap_count,
        non_monotonic_frame_count=non_monotonic_frame_count,
        tlv_type_counts=dict(sorted(tlv_type_counts.items())),
    )


def print_summary(summary: SmokeTestSummary, minimum_packet_count: int) -> None:
    """Print a compact, human-readable test summary."""
    print("Smoke test summary")
    print(f"  bytes_read: {summary.bytes_read}")
    print(f"  valid_packets: {summary.valid_packet_count}")
    print(f"  invalid_packets: {summary.invalid_packet_count}")
    print(f"  first_frame: {summary.first_frame_number}")
    print(f"  last_frame: {summary.last_frame_number}")
    print(f"  frame_gaps: {summary.frame_gap_count}")
    print(f"  non_monotonic_frames: {summary.non_monotonic_frame_count}")
    print(f"  tlv_types: {summary.tlv_type_counts}")
    print(
        "  result: " + ("PASS" if summary.passed(minimum_packet_count) else "FAIL"),
    )


def print_cli_session_result(session: CliSessionResult) -> None:
    """Print a compact summary of the CLI configuration session."""
    print(f"sent_config_lines: {len(session.commands)}")
    for command_result in session.commands:
        for response in command_result.responses:
            print(f"cli: {response}")


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    if args.list_ports:
        for port_description in list_serial_ports():
            print(port_description)
        return 0

    if not args.data_port:
        parser.error("--data-port is required unless --list-ports is used.")

    if args.config and not args.cli_port:
        parser.error("--cli-port is required when --config is provided.")

    if args.config:
        session = send_config(
            cli_port=args.cli_port,
            cli_baudrate=args.cli_baudrate,
            config_path=args.config,
            stream_output=True,
        )

        if not session.startup_prompt_seen:
            print("CLI did not become ready before config")
            return 2

        failed_command = session.failed_command
        if failed_command is not None:
            print("Config failed before data capture")
            print(f"  failed_command: {failed_command.command}")
            return 2

        if any(not command_result.responses for command_result in session.commands):
            stalled_command = next(
                command_result.command
                for command_result in session.commands
                if not command_result.responses
            )
            print("Config timed out before data capture")
            print(f"  stalled_command: {stalled_command}")
            return 2

    summary = run_smoke_test(
        data_port=args.data_port,
        data_baudrate=args.data_baudrate,
        duration_seconds=args.duration,
        read_size=args.read_size,
        verbose=args.verbose,
    )
    print_summary(summary, args.min_packets)
    return 0 if summary.passed(args.min_packets) else 1


if __name__ == "__main__":
    sys.exit(main())
