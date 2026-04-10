"""Typer command registration for firmware mmWave workflows."""

from __future__ import annotations

import sys
from pathlib import Path  # noqa: TC003
from typing import Annotated

import typer
from rich.console import Console

from vassago.firmware.mmwave import config as mmwave_config
from vassago.firmware.mmwave import ports as mmwave_ports
from vassago.firmware.mmwave import smoke_test as mmwave_smoke_test
from vassago.firmware.mmwave import ui as mmwave_ui

console = Console()


def register_commands(app: typer.Typer) -> None:
    """Attach mmWave subcommands to an existing Typer app."""
    app.command("list-ports")(handle_list_ports)
    app.command("probe-ports")(handle_probe_ports)
    app.command("smoke-test")(handle_smoke_test)


def handle_list_ports() -> None:
    """List serial ports visible to the host."""
    mmwave_ui.render_serial_ports(console, mmwave_ports.list_serial_ports())


def handle_probe_ports(
    cli_baudrate: Annotated[
        int,
        typer.Option(help="CLI UART baudrate."),
    ] = mmwave_smoke_test.DEFAULT_CLI_BAUDRATE,
    data_baudrate: Annotated[
        int,
        typer.Option(help="Data UART baudrate."),
    ] = mmwave_smoke_test.DEFAULT_DATA_BAUDRATE,
    probe_duration: Annotated[
        float,
        typer.Option(help="How long to listen to each port during probe."),
    ] = mmwave_smoke_test.DEFAULT_PROBE_DURATION_SECONDS,
    read_size: Annotated[
        int,
        typer.Option(help="Bytes requested per serial read."),
    ] = mmwave_smoke_test.DEFAULT_READ_SIZE,
) -> None:
    """Probe candidate serial ports and infer CLI/Data roles."""
    candidates = mmwave_ports.list_candidate_mmwave_ports(
        mmwave_ports.list_serial_ports(),
    )
    if not candidates:
        console.print("No mmWave-style candidate ports found.")
        raise typer.Exit(code=1)

    results = mmwave_smoke_test.collect_probe_results(
        cli_baudrate=cli_baudrate,
        data_baudrate=data_baudrate,
        probe_duration_seconds=probe_duration,
        read_size=read_size,
        candidate_ports=candidates,
    )
    suggested_cli_port, suggested_data_port = mmwave_smoke_test.infer_port_roles(
        results,
    )
    mmwave_ui.render_probe_results(
        console,
        results,
        suggested_cli_port=suggested_cli_port,
        suggested_data_port=suggested_data_port,
    )


def handle_smoke_test(  # noqa: PLR0913
    data_port: Annotated[
        str | None,
        typer.Option(help="Data UART port."),
    ] = None,
    cli_port: Annotated[
        str | None,
        typer.Option(help="CLI UART port for cfg upload."),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option(help="Explicit path to a cfg file."),
    ] = None,
    config_id: Annotated[
        str | None,
        typer.Option(help="Curated cfg id, for example baseline_pointcloud."),
    ] = None,
    duration: Annotated[
        float,
        typer.Option(help="How long to read from the data port."),
    ] = mmwave_smoke_test.DEFAULT_DURATION_SECONDS,
    min_packets: Annotated[
        int,
        typer.Option(help="Minimum valid packets required to pass."),
    ] = mmwave_smoke_test.DEFAULT_MIN_PACKETS,
    read_size: Annotated[
        int,
        typer.Option(help="Bytes requested per serial read."),
    ] = mmwave_smoke_test.DEFAULT_READ_SIZE,
    cli_baudrate: Annotated[
        int,
        typer.Option(help="CLI UART baudrate."),
    ] = mmwave_smoke_test.DEFAULT_CLI_BAUDRATE,
    data_baudrate: Annotated[
        int,
        typer.Option(help="Data UART baudrate."),
    ] = mmwave_smoke_test.DEFAULT_DATA_BAUDRATE,
    verbose: Annotated[
        bool,
        typer.Option(help="Print each valid frame while reading."),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive/--no-interactive",
            help="Allow interactive cfg and port selection when args are missing.",
        ),
    ] = True,
) -> None:
    """Optionally send a cfg, then validate that the data UART emits packets."""
    resolved_interactive = interactive and sys.stdin.isatty()
    selected_config_path = _resolve_config_path(
        explicit_config_path=config,
        config_id=config_id,
        interactive=resolved_interactive,
    )
    selected_cli_port, selected_data_port = _resolve_ports(
        cli_port=cli_port,
        data_port=data_port,
        cli_baudrate=cli_baudrate,
        data_baudrate=data_baudrate,
        read_size=read_size,
        interactive=resolved_interactive,
        require_cli=selected_config_path is not None,
    )
    _validate_required_ports(
        data_port=selected_data_port,
        cli_port=selected_cli_port,
        config_path=selected_config_path,
    )

    if selected_config_path is not None:
        _send_selected_config(
            cli_port=selected_cli_port,
            cli_baudrate=cli_baudrate,
            config_path=selected_config_path,
        )

    summary = mmwave_smoke_test.run_smoke_test(
        data_port=selected_data_port,
        data_baudrate=data_baudrate,
        duration_seconds=duration,
        read_size=read_size,
        verbose=verbose,
    )
    mmwave_ui.render_smoke_test_summary(
        console,
        summary,
        minimum_packet_count=min_packets,
    )
    raise typer.Exit(code=0 if summary.passed(min_packets) else 1)


def _validate_required_ports(
    *,
    data_port: str | None,
    cli_port: str | None,
    config_path: Path | None,
) -> None:
    """Fail early when required ports are still missing after resolution."""
    if data_port is None:
        message = (
            "A data port is required. Pass --data-port or enable interactive mode."
        )
        raise typer.BadParameter(message)

    if config_path is not None and cli_port is None:
        message = "A CLI port is required when a cfg file is provided."
        raise typer.BadParameter(message)


def _send_selected_config(
    *,
    cli_port: str | None,
    cli_baudrate: int,
    config_path: Path,
) -> None:
    """Upload one selected cfg and surface human-readable failures."""
    console.print(f"Using cfg: {config_path}")
    session = mmwave_smoke_test.send_config(
        cli_port=cli_port,
        cli_baudrate=cli_baudrate,
        config_path=config_path,
        stream_output=True,
    )

    if not session.startup_prompt_seen:
        _exit_config_failure(
            title="CLI did not become ready before config.",
            failed_command=None,
            exit_code=2,
        )

    failed_command = session.failed_command
    if failed_command is not None:
        _exit_config_failure(
            title="Config failed before data capture.",
            failed_command=failed_command.command,
            exit_code=2,
        )

    stalled_command = next(
        (
            command_result.command
            for command_result in session.commands
            if not command_result.responses
        ),
        None,
    )
    if stalled_command is not None:
        _exit_config_failure(
            title="Config timed out before data capture.",
            failed_command=stalled_command,
            exit_code=2,
        )


def _exit_config_failure(
    *,
    title: str,
    failed_command: str | None,
    exit_code: int,
) -> None:
    """Render a config failure plus recovery hint, then exit."""
    console.print(title)
    if failed_command is not None:
        console.print(f"failed_command: {failed_command}")
    console.print(
        "hint:",
        mmwave_smoke_test.build_recovery_hint(failed_command=failed_command),
    )
    raise typer.Exit(code=exit_code)


def _resolve_config_path(
    *,
    explicit_config_path: Path | None,
    config_id: str | None,
    interactive: bool,
) -> Path | None:
    """Resolve the cfg path from explicit args or interactive selection."""
    if explicit_config_path is not None and config_id is not None:
        message = "Pass either --config or --config-id, not both."
        raise typer.BadParameter(message)

    if explicit_config_path is not None:
        resolved_path = explicit_config_path.expanduser().resolve()
        if not resolved_path.is_file():
            message = f"Config file not found: {resolved_path}"
            raise typer.BadParameter(message)
        return resolved_path

    if config_id is not None:
        return mmwave_config.get_known_config(config_id).path.resolve()

    if not interactive:
        return None

    configs = mmwave_config.list_known_configs()
    mmwave_ui.render_known_configs(console, configs)
    selected_config = mmwave_ui.prompt_for_known_config(configs)
    return None if selected_config is None else selected_config.path.resolve()


def _resolve_ports(
    *,
    cli_port: str | None,
    data_port: str | None,
    cli_baudrate: int,
    data_baudrate: int,
    read_size: int,
    interactive: bool,
    require_cli: bool,
) -> tuple[str | None, str | None]:
    """Resolve missing ports from probe results when interactive mode is enabled."""
    if data_port is not None and (cli_port is not None or not require_cli):
        return cli_port, data_port

    if not interactive:
        return cli_port, data_port

    visible_ports = mmwave_ports.list_serial_ports()
    candidate_ports = mmwave_ports.list_candidate_mmwave_ports(visible_ports)
    if not candidate_ports:
        candidate_ports = visible_ports
        console.print(
            "No mmWave-style candidate ports found. Falling back to all visible ports.",
        )

    probe_results = mmwave_smoke_test.collect_probe_results(
        cli_baudrate=cli_baudrate,
        data_baudrate=data_baudrate,
        probe_duration_seconds=mmwave_smoke_test.DEFAULT_PROBE_DURATION_SECONDS,
        read_size=read_size,
        candidate_ports=candidate_ports,
    )
    suggested_cli_port, suggested_data_port = mmwave_smoke_test.infer_port_roles(
        probe_results,
    )
    mmwave_ui.render_probe_results(
        console,
        probe_results,
        suggested_cli_port=suggested_cli_port,
        suggested_data_port=suggested_data_port,
    )
    port_devices = [port.device for port in candidate_ports]

    resolved_cli_port = cli_port
    if require_cli and resolved_cli_port is None:
        resolved_cli_port = mmwave_ui.prompt_for_port(
            message="Choose the CLI port",
            ports=port_devices,
            default_port=suggested_cli_port,
        )

    resolved_data_port = data_port
    if resolved_data_port is None:
        resolved_data_port = mmwave_ui.prompt_for_port(
            message="Choose the Data port",
            ports=port_devices,
            default_port=suggested_data_port,
        )

    return resolved_cli_port, resolved_data_port
