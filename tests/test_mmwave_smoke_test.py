"""Tests for smoke-test helpers and cfg upload logic."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Self

from vassago.firmware.mmwave.smoke_test import DEFAULT_CLI_BAUDRATE
from vassago.firmware.mmwave.smoke_test import CliSessionResult
from vassago.firmware.mmwave.smoke_test import PortProbeResult
from vassago.firmware.mmwave.smoke_test import build_recovery_hint
from vassago.firmware.mmwave.smoke_test import infer_port_roles
from vassago.firmware.mmwave.smoke_test import load_config_lines
from vassago.firmware.mmwave.smoke_test import send_config

if TYPE_CHECKING:
    from pathlib import Path


def test_load_config_lines_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    config_path = tmp_path / "test.cfg"
    config_path.write_text(
        "\n% comment\nsensorStop % inline note\n\n# note\nsensorStart # tail note\n",
        encoding="utf-8",
    )

    assert load_config_lines(config_path) == ["sensorStop", "sensorStart"]


def test_infer_port_roles_prefers_unique_cli_and_busiest_data_port() -> None:
    cli_port, data_port = infer_port_roles(
        [
            PortProbeResult(
                port="/dev/cu.SLAB_USBtoUART5",
                description="CLI",
                cli_prompt_seen=True,
                cli_response_lines=("mmwDemo:/>",),
                data_bytes_read=0,
                valid_packet_count=0,
                invalid_packet_count=0,
            ),
            PortProbeResult(
                port="/dev/cu.SLAB_USBtoUART6",
                description="DATA",
                cli_prompt_seen=False,
                cli_response_lines=(),
                data_bytes_read=8192,
                valid_packet_count=4,
                invalid_packet_count=0,
            ),
        ],
    )

    assert cli_port == "/dev/cu.SLAB_USBtoUART5"
    assert data_port == "/dev/cu.SLAB_USBtoUART6"


def test_infer_port_roles_prefers_slab_alias_when_driver_exposes_duplicates() -> None:
    cli_port, data_port = infer_port_roles(
        [
            PortProbeResult(
                port="/dev/cu.SLAB_USBtoUART",
                description="DATA alias A",
                cli_prompt_seen=False,
                cli_response_lines=(),
                data_bytes_read=0,
                valid_packet_count=0,
                invalid_packet_count=0,
                serial_number="008ACB32",
                location="1-1.2",
                vid=0x10C4,
                pid=0xEA70,
            ),
            PortProbeResult(
                port="/dev/cu.SLAB_USBtoUART4",
                description="CLI alias A",
                cli_prompt_seen=True,
                cli_response_lines=("mmwDemo:/>",),
                data_bytes_read=0,
                valid_packet_count=0,
                invalid_packet_count=0,
                serial_number="008ACB32",
                location="1-1.2",
                vid=0x10C4,
                pid=0xEA70,
            ),
            PortProbeResult(
                port="/dev/cu.usbserial-008ACB320",
                description="CLI alias B",
                cli_prompt_seen=True,
                cli_response_lines=("mmwDemo:/>",),
                data_bytes_read=0,
                valid_packet_count=0,
                invalid_packet_count=0,
                serial_number="008ACB32",
                location="1-1.2",
                vid=0x10C4,
                pid=0xEA70,
            ),
            PortProbeResult(
                port="/dev/cu.usbserial-008ACB321",
                description="DATA alias B",
                cli_prompt_seen=False,
                cli_response_lines=(),
                data_bytes_read=0,
                valid_packet_count=0,
                invalid_packet_count=0,
                serial_number="008ACB32",
                location="1-1.2",
                vid=0x10C4,
                pid=0xEA70,
            ),
        ],
    )

    assert cli_port == "/dev/cu.SLAB_USBtoUART4"
    assert data_port == "/dev/cu.SLAB_USBtoUART"


def test_build_recovery_hint_special_cases_sensor_start() -> None:
    assert "baseline cfg" in build_recovery_hint(failed_command="sensorStart")
    assert "probe-ports" in build_recovery_hint()
    assert "unsupported command" in build_recovery_hint(
        failed_command="bpmCfg -1 0 0 0",
    )


def test_send_config_collects_startup_and_command_responses(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "test.cfg"
    config_path.write_text("sensorStop\nsensorStart\n", encoding="utf-8")
    fake_serial = FakeSerial(
        responses=[
            b"mmwDemo:/>\r\n",
            b"Done\r\nmmwDemo:/>\r\n",
            b"Done\r\nmmwDemo:/>\r\n",
        ],
    )
    monkeypatch.setattr(
        "vassago.firmware.mmwave.smoke_test.serial.Serial",
        lambda **_kwargs: fake_serial,
    )

    session = send_config(
        cli_port="/dev/cu.SLAB_USBtoUART5",
        cli_baudrate=DEFAULT_CLI_BAUDRATE,
        config_path=config_path,
        stream_output=False,
    )

    assert isinstance(session, CliSessionResult)
    assert session.startup_prompt_seen is True
    assert [command.command for command in session.commands] == [
        "sensorStop",
        "sensorStart",
    ]
    assert fake_serial.written == [b"sensorStop\n", b"sensorStart\n"]


class FakeSerial:
    """Minimal serial stub used to test cfg upload sequencing."""

    def __init__(self, *, responses: list[bytes]) -> None:
        self._responses = responses
        self.written: list[bytes] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def reset_input_buffer(self) -> None:
        return None

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def read_all(self) -> bytes:
        if self._responses:
            return self._responses.pop(0)
        return b""
