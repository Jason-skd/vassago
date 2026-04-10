"""Terminal UI helpers for the mmWave bring-up workflow."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import questionary
from rich.table import Table

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rich.console import Console

    from vassago.firmware.mmwave.config import KnownMmwaveConfig
    from vassago.firmware.mmwave.ports import SerialPortInfo
    from vassago.firmware.mmwave.protocol import SmokeTestSummary
    from vassago.firmware.mmwave.smoke_test import PortProbeResult


def render_serial_ports(
    console: Console,
    port_infos: Sequence[SerialPortInfo],
) -> None:
    """Render a compact table of visible serial ports."""
    table = Table(title="Visible Serial Ports")
    table.add_column("Device")
    table.add_column("Description")
    table.add_column("Manufacturer")

    for port in port_infos:
        table.add_row(port.device, port.description, port.manufacturer or "-")

    if not port_infos:
        table.add_row("-", "No visible ports", "-")

    console.print(table)


def render_probe_results(
    console: Console,
    probe_results: Sequence[PortProbeResult],
    *,
    suggested_cli_port: str | None,
    suggested_data_port: str | None,
) -> None:
    """Render probe results plus suggested roles."""
    table = Table(title="Port Probe Summary")
    table.add_column("Port")
    table.add_column("Description")
    table.add_column("CLI Prompt")
    table.add_column("Bytes Read", justify="right")
    table.add_column("Valid Packets", justify="right")
    table.add_column("Invalid Packets", justify="right")

    for result in probe_results:
        table.add_row(
            result.port,
            result.description,
            "yes" if result.cli_prompt_seen else "no",
            str(result.data_bytes_read),
            str(result.valid_packet_count),
            str(result.invalid_packet_count),
        )

    if not probe_results:
        table.add_row("-", "-", "-", "0", "0", "0")

    console.print(table)
    console.print(f"Suggested CLI port: {suggested_cli_port}")
    console.print(f"Suggested Data port: {suggested_data_port}")


def render_known_configs(
    console: Console,
    configs: Sequence[KnownMmwaveConfig],
) -> None:
    """Render the curated cfg registry."""
    table = Table(title="Known mmWave cfg Files")
    table.add_column("Config ID")
    table.add_column("Label")
    table.add_column("Risk")
    table.add_column("Bring-Up")
    table.add_column("Path")

    for config in configs:
        table.add_row(
            config.config_id,
            config.label,
            config.risk,
            "yes" if config.recommended_for_bringup else "no",
            str(config.path),
        )

    console.print(table)


def render_smoke_test_summary(
    console: Console,
    summary: SmokeTestSummary,
    *,
    minimum_packet_count: int,
) -> None:
    """Render a compact smoke-test summary."""
    table = Table(title="Smoke Test Summary")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("bytes_read", str(summary.bytes_read))
    table.add_row("valid_packets", str(summary.valid_packet_count))
    table.add_row("invalid_packets", str(summary.invalid_packet_count))
    table.add_row("first_frame", str(summary.first_frame_number))
    table.add_row("last_frame", str(summary.last_frame_number))
    table.add_row("frame_gaps", str(summary.frame_gap_count))
    table.add_row(
        "non_monotonic_frames",
        str(summary.non_monotonic_frame_count),
    )
    table.add_row("tlv_types", str(summary.tlv_type_counts))
    table.add_row(
        "result",
        "PASS" if summary.passed(minimum_packet_count) else "FAIL",
    )
    console.print(table)


def prompt_for_known_config(
    configs: Sequence[KnownMmwaveConfig],
) -> KnownMmwaveConfig | None:
    """Prompt the operator to choose a curated cfg or skip config upload."""
    choices = [
        questionary.Choice(
            title=(
                f"{config.label} [{config.config_id}] "
                f"risk={config.risk} path={config.path}"
            ),
            value=config,
        )
        for config in configs
    ]
    choices.append(
        questionary.Choice(
            title="Listen only (skip cfg upload)",
            value=None,
        ),
    )
    return questionary.select(
        "Choose a cfg for this smoke test",
        choices=choices,
    ).ask()


def prompt_for_port(
    *,
    message: str,
    ports: Sequence[str],
    default_port: str | None = None,
) -> str:
    """Prompt the operator to choose one port from a list."""
    default_value = default_port if default_port in ports else None
    response = questionary.select(
        message,
        choices=list(ports),
        default=default_value,
    ).ask()
    if response is None:
        msg = "Port selection was cancelled."
        raise RuntimeError(msg)
    return response


def prompt_for_path(
    *,
    message: str,
    default: Path | None = None,
) -> Path:
    """Prompt for a filesystem path when curated cfg choices are insufficient."""
    default_text = str(default) if default is not None else ""
    response = questionary.path(message, default=default_text).ask()
    if response is None:
        msg = "Path input was cancelled."
        raise RuntimeError(msg)
    return Path(response).expanduser().resolve()
