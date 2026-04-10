"""CLI routing tests for the smoke-test slice."""

from __future__ import annotations

from typer.testing import CliRunner

from vassago.cli import app
from vassago.firmware.mmwave.ports import SerialPortInfo
from vassago.firmware.mmwave.smoke_test import PortProbeResult

runner = CliRunner()


def test_list_ports_command_renders_visible_ports(monkeypatch) -> None:
    monkeypatch.setattr(
        "vassago.firmware.mmwave.cli.mmwave_ports.list_serial_ports",
        lambda: [
            SerialPortInfo(
                device="/dev/cu.SLAB_USBtoUART5",
                description="CP210x USB to UART Bridge",
                manufacturer="Silicon Labs",
            ),
        ],
    )

    result = runner.invoke(app, ["firmware", "mmwave", "list-ports"])

    assert result.exit_code == 0
    assert "/dev/cu.SLAB_USBtoUART5" in result.output


def test_probe_ports_command_renders_suggested_roles(monkeypatch) -> None:
    candidate_ports = [
        SerialPortInfo(
            device="/dev/cu.SLAB_USBtoUART5",
            description="CP210x USB to UART Bridge",
            manufacturer="Silicon Labs",
        ),
        SerialPortInfo(
            device="/dev/cu.SLAB_USBtoUART6",
            description="CP210x USB to UART Bridge",
            manufacturer="Silicon Labs",
        ),
    ]
    monkeypatch.setattr(
        "vassago.firmware.mmwave.cli.mmwave_ports.list_serial_ports",
        lambda: candidate_ports,
    )
    monkeypatch.setattr(
        "vassago.firmware.mmwave.cli.mmwave_ports.list_candidate_mmwave_ports",
        lambda _visible: candidate_ports,
    )
    monkeypatch.setattr(
        "vassago.firmware.mmwave.cli.mmwave_smoke_test.collect_probe_results",
        lambda **_kwargs: [
            PortProbeResult(
                port="/dev/cu.SLAB_USBtoUART5",
                description="CP210x USB to UART Bridge",
                cli_prompt_seen=True,
                cli_response_lines=("mmwDemo:/>",),
                data_bytes_read=0,
                valid_packet_count=0,
                invalid_packet_count=0,
            ),
            PortProbeResult(
                port="/dev/cu.SLAB_USBtoUART6",
                description="CP210x USB to UART Bridge",
                cli_prompt_seen=False,
                cli_response_lines=(),
                data_bytes_read=4096,
                valid_packet_count=5,
                invalid_packet_count=0,
            ),
        ],
    )

    result = runner.invoke(app, ["firmware", "mmwave", "probe-ports"])

    assert result.exit_code == 0
    assert "Suggested CLI port: /dev/cu.SLAB_USBtoUART5" in result.output
    assert "Suggested Data port: /dev/cu.SLAB_USBtoUART6" in result.output
