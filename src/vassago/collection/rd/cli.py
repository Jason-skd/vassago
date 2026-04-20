"""Typer command registration for RD collection workflows."""

from __future__ import annotations

import sys
from pathlib import Path  # noqa: TC003
from typing import Annotated

import typer
from rich.console import Console

from vassago.collection.rd import capture as collection_capture
from vassago.collection.rd import config as collection_config
from vassago.collection.rd import offline_qc as collection_offline_qc
from vassago.collection.rd import session as collection_session
from vassago.collection.rd import ui as collection_ui
from vassago.collection.rd.paths import to_repo_relative_path
from vassago.collection.rd.qc_contract import QC_SEVERITY_ERROR
from vassago.collection.rd.qc_contract import QC_SEVERITY_INFO
from vassago.collection.rd.qc_contract import QC_SEVERITY_WARN
from vassago.collection.rd.qc_contract import QcReport
from vassago.firmware.mmwave import config as mmwave_config
from vassago.firmware.mmwave import ports as mmwave_ports
from vassago.firmware.mmwave import smoke_test as mmwave_smoke_test
from vassago.firmware.mmwave import ui as mmwave_ui

console = Console()


def register_commands(app: typer.Typer) -> None:
    """Attach RD collection subcommands to an existing Typer app."""
    app.command("list-configs")(handle_list_configs)
    app.command("list-sessions")(handle_list_sessions)
    app.command("init-session")(handle_init_session)
    app.command("run-session")(handle_run_session)
    app.command("resume-session")(handle_run_session)
    app.command("offline-qc")(handle_offline_qc)
    app.command("offline-qc-all")(handle_offline_qc_all)


def handle_list_configs() -> None:
    """List the repository-managed RD collection configs."""
    profiles = collection_config.list_collection_profiles()
    collection_ui.render_collection_profiles(console, profiles)


def handle_list_sessions(
    sessions_root: Annotated[
        Path,
        typer.Option(help="Directory used for collection session manifests."),
    ] = collection_session.DEFAULT_SESSIONS_ROOT,
) -> None:
    """List non-completed collection sessions."""
    sessions = collection_session.list_unfinished_sessions(
        sessions_root=sessions_root,
    )
    collection_ui.render_sessions(console, sessions)


def handle_init_session(  # noqa: PLR0913
    config: Annotated[
        Path | None,
        typer.Option(help="Explicit path to a collection profile TOML."),
    ] = None,
    config_id: Annotated[
        str | None,
        typer.Option(help="Curated collection config id."),
    ] = None,
    collection_type: Annotated[
        str,
        typer.Option(
            help=(
                "Session collection type. Background types are reserved in the "
                "contract but not yet runnable."
            ),
        ),
    ] = collection_session.COLLECTION_TYPE_GESTURE,
    subject_name: Annotated[
        str | None,
        typer.Option(help="Unique subject_name key for this session."),
    ] = None,
    hand: Annotated[
        str | None,
        typer.Option(help="Hand used for the gesture."),
    ] = None,
    distance_m: Annotated[
        float | None,
        typer.Option(help="Subject distance to radar in meters."),
    ] = None,
    angle_deg: Annotated[
        float | None,
        typer.Option(help="Subject angle relative to radar center in degrees."),
    ] = None,
    environment: Annotated[
        str | None,
        typer.Option(help="Environment id from the selected collection profile."),
    ] = None,
    operator_name: Annotated[
        str | None,
        typer.Option(help="Operator responsible for this session."),
    ] = None,
    note: Annotated[
        str | None,
        typer.Option(help="Optional session note."),
    ] = None,
    radar_id: Annotated[
        str | None,
        typer.Option(help="Radar device identifier."),
    ] = None,
    firmware_id: Annotated[
        str | None,
        typer.Option(help="Firmware or demo identifier."),
    ] = None,
    firmware_config_id: Annotated[
        str | None,
        typer.Option(
            help="Override the mmWave cfg config_id used for this session.",
        ),
    ] = None,
    gesture: Annotated[
        str | None,
        typer.Option(help="Gesture selected from the collection profile."),
    ] = None,
    cli_port: Annotated[
        str | None,
        typer.Option(help="CLI UART port."),
    ] = None,
    data_port: Annotated[
        str | None,
        typer.Option(help="Data UART port."),
    ] = None,
    data_baudrate: Annotated[
        int | None,
        typer.Option(help="Data UART baudrate override."),
    ] = None,
    sessions_root: Annotated[
        Path,
        typer.Option(help="Directory used for collection session manifests."),
    ] = collection_session.DEFAULT_SESSIONS_ROOT,
    run_after_init: Annotated[
        bool,
        typer.Option(
            "--run/--no-run",
            help="Start the collection state machine after manifest init.",
        ),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive/--no-interactive",
            help="Allow interactive config and field selection when args are missing.",
        ),
    ] = True,
    visualizer: Annotated[
        bool,
        typer.Option(
            "--visualizer/--no-visualizer",
            help="Enable the experimental live point-cloud visualizer during run.",
        ),
    ] = False,
) -> None:
    """Create a collection session manifest from the configured contract."""
    resolved_interactive = interactive and sys.stdin.isatty()
    profile = _resolve_profile(
        config_path=config,
        config_id=config_id,
        interactive=resolved_interactive,
    )
    selected_collection_type = _resolve_collection_type(
        collection_type=collection_type,
        interactive=resolved_interactive,
    )
    selected_gesture = _resolve_gesture(
        gesture=gesture,
        profile=profile,
        interactive=resolved_interactive,
    )
    selected_firmware_config_id = _resolve_firmware_config_id(
        value=firmware_config_id,
        profile=profile,
        interactive=resolved_interactive,
    )
    selected_cli_port, selected_data_port = _resolve_ports(
        cli_port=cli_port,
        data_port=data_port,
        profile=profile,
        interactive=resolved_interactive,
    )

    session_input = collection_session.SessionInitInput(
        profile=profile,
        subject_name=_resolve_required_text(
            value=subject_name,
            interactive=resolved_interactive,
            message="subject_name",
        ),
        hand=_resolve_choice(
            value=hand,
            choices=("left", "right"),
            default=profile.defaults.hand,
            interactive=resolved_interactive,
            message="Choose hand",
        ),
        distance_m=_resolve_optional_float(
            value=distance_m,
            default=profile.defaults.distance_m,
            interactive=resolved_interactive,
            message="distance_m",
        ),
        angle_deg=_resolve_optional_float(
            value=angle_deg,
            default=profile.defaults.angle_deg,
            interactive=resolved_interactive,
            message="angle_deg",
        ),
        environment=_resolve_choice(
            value=environment,
            choices=profile.environments,
            default=profile.defaults.environment,
            interactive=resolved_interactive,
            message="Choose environment",
        ),
        operator_name=_resolve_required_text(
            value=operator_name,
            interactive=resolved_interactive,
            message="operator_name",
        ),
        note=_resolve_optional_text(
            value=note,
            interactive=resolved_interactive,
            message="note",
        ),
        radar_id=_resolve_required_text(
            value=radar_id,
            default=profile.defaults.radar_id,
            interactive=resolved_interactive,
            message="radar_id",
        ),
        firmware_id=_resolve_required_text(
            value=firmware_id,
            default=profile.defaults.firmware_id,
            interactive=resolved_interactive,
            message="firmware_id",
        ),
        gesture=selected_gesture,
        firmware_config_id=selected_firmware_config_id,
        cli_port=selected_cli_port,
        data_port=selected_data_port,
        data_baudrate=data_baudrate or profile.serial.data_baudrate,
        collection_type=selected_collection_type,
    )
    manifest_path, manifest = collection_session.initialize_session(
        session_input=session_input,
        sessions_root=sessions_root,
    )
    collection_ui.render_session_summary(
        console,
        manifest_path=manifest_path,
        manifest=manifest,
    )

    if run_after_init:
        summary = collection_capture.run_session(
            manifest_path,
            enable_visualizer=visualizer,
        )
        console.print(
            f"accepted_take_count: {summary.accepted_take_count}\n"
            f"remaining_take_count: {summary.remaining_take_count}",
        )


def handle_run_session(
    manifest: Annotated[
        Path | None,
        typer.Option(help="Path to an existing collection manifest."),
    ] = None,
    sessions_root: Annotated[
        Path,
        typer.Option(help="Directory used for collection session manifests."),
    ] = collection_session.DEFAULT_SESSIONS_ROOT,
    read_size: Annotated[
        int,
        typer.Option(help="Bytes requested per serial read."),
    ] = mmwave_smoke_test.DEFAULT_READ_SIZE,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive/--no-interactive",
            help=(
                "Allow interactive unfinished-session selection when manifest "
                "is absent."
            ),
        ),
    ] = True,
    visualizer: Annotated[
        bool,
        typer.Option(
            "--visualizer/--no-visualizer",
            help="Enable the experimental live point-cloud visualizer during run.",
        ),
    ] = False,
) -> None:
    """Run or resume one collection session."""
    resolved_interactive = interactive and sys.stdin.isatty()
    selected_manifest = manifest
    if selected_manifest is None:
        sessions = collection_session.list_unfinished_sessions(
            sessions_root=sessions_root,
        )
        if not sessions:
            msg = "No unfinished collection sessions were found."
            raise typer.BadParameter(msg)
        collection_ui.render_sessions(console, sessions)
        if not resolved_interactive:
            msg = "Pass --manifest or enable interactive mode to choose a session."
            raise typer.BadParameter(msg)
        selected_manifest = collection_ui.prompt_for_session(sessions).manifest_path

    summary = collection_capture.run_session(
        selected_manifest,
        read_size=read_size,
        enable_visualizer=visualizer,
    )
    manifest_data = collection_session.load_manifest(selected_manifest)
    collection_ui.render_session_summary(
        console,
        manifest_path=selected_manifest,
        manifest=manifest_data,
    )
    console.print(
        f"accepted_take_count: {summary.accepted_take_count}\n"
        f"remaining_take_count: {summary.remaining_take_count}",
    )


def handle_offline_qc(
    manifest: Annotated[
        Path,
        typer.Option(help="Path to an existing collection manifest."),
    ],
) -> None:
    """Run offline QC against one persisted collection manifest."""
    report = collection_offline_qc.run_offline_qc(manifest_path=manifest)
    _render_offline_qc_report(manifest_path=manifest, report=report)

    error_count = len(report.findings_for(severity=QC_SEVERITY_ERROR))
    raise typer.Exit(code=1 if error_count else 0)


def handle_offline_qc_all(
    sessions_root: Annotated[
        Path,
        typer.Option(help="Directory scanned for collection session manifests."),
    ] = collection_session.DEFAULT_SESSIONS_ROOT,
) -> None:
    """Run offline QC across every discovered persisted collection manifest."""
    run_result = collection_offline_qc.run_offline_qc_all(sessions_root=sessions_root)
    _render_offline_qc_run_result(
        sessions_root=sessions_root,
        run_result=run_result,
    )
    raise typer.Exit(code=1 if run_result.report.has_errors else 0)


def _resolve_profile(
    *,
    config_path: Path | None,
    config_id: str | None,
    interactive: bool,
) -> collection_config.CollectionProfile:
    """Resolve the selected collection profile from args or interactive choice."""
    if config_path is not None and config_id is not None:
        msg = "Pass either --config or --config-id, not both."
        raise typer.BadParameter(msg)

    if config_path is not None:
        return collection_config.load_collection_profile(config_path)

    if config_id is not None:
        return collection_config.get_collection_profile(config_id)

    profiles = collection_config.list_collection_profiles()
    if len(profiles) == 1:
        return profiles[0]

    if interactive:
        collection_ui.render_collection_profiles(console, profiles)
        return collection_ui.prompt_for_collection_profile(profiles)

    msg = "Pass --config-id or enable interactive mode to choose a collection config."
    raise typer.BadParameter(msg)


def _render_offline_qc_report(*, manifest_path: Path, report: QcReport) -> None:
    """Render a compact offline-QC summary suitable for CLI and hooks."""
    error_count = len(report.findings_for(severity=QC_SEVERITY_ERROR))
    warn_count = len(report.findings_for(severity=QC_SEVERITY_WARN))
    info_count = len(report.findings_for(severity=QC_SEVERITY_INFO))
    result = "fail" if error_count else "pass"
    if warn_count and not error_count:
        result = "pass_with_warnings"

    console.print("Offline QC Summary")
    console.print(f"manifest: {to_repo_relative_path(manifest_path)}")
    console.print(f"result: {result}")
    console.print(f"errors: {error_count}")
    console.print(f"warnings: {warn_count}")
    console.print(f"info: {info_count}")

    for finding in report.findings:
        header = f"[{finding.severity}] {finding.plugin}:{finding.code}"
        details: list[str] = []
        if finding.take_id is not None:
            details.append(f"take={finding.take_id}")
        if finding.field_path is not None:
            details.append(f"field={finding.field_path}")
        suffix = f" {' '.join(details)}" if details else ""
        console.print(f"{header}{suffix}")
        console.print(f"  {finding.message}")


def _render_offline_qc_run_result(
    *,
    sessions_root: Path,
    run_result: collection_offline_qc.OfflineQcRunResult,
) -> None:
    """Render one full-repository offline-QC run plus per-manifest details."""
    report = run_result.report
    error_count = len(report.findings_for(severity=QC_SEVERITY_ERROR))
    warn_count = len(report.findings_for(severity=QC_SEVERITY_WARN))
    info_count = len(report.findings_for(severity=QC_SEVERITY_INFO))
    result = "fail" if error_count else "pass"
    if warn_count and not error_count:
        result = "pass_with_warnings"

    console.print("Offline QC Validation Summary")
    console.print(f"sessions_root: {to_repo_relative_path(sessions_root)}")
    console.print(f"checked_manifests: {run_result.checked_manifest_count}")
    console.print(f"result: {result}")
    console.print(f"errors: {error_count}")
    console.print(f"warnings: {warn_count}")
    console.print(f"info: {info_count}")

    if not run_result.manifest_results:
        return

    console.print()
    for index, manifest_result in enumerate(run_result.manifest_results):
        if index:
            console.print()
        _render_offline_qc_report(
            manifest_path=manifest_result.manifest_path,
            report=manifest_result.report,
        )


def _resolve_gesture(
    *,
    gesture: str | None,
    profile: collection_config.CollectionProfile,
    interactive: bool,
) -> str:
    """Resolve gesture from args or interactive selection."""
    if gesture is not None:
        if gesture not in profile.gestures:
            msg = f"Unknown gesture {gesture!r} for config {profile.config_id}."
            raise typer.BadParameter(msg)
        return gesture

    if interactive:
        return collection_ui.prompt_for_choice(
            message="Choose gesture",
            choices=profile.gestures,
        )

    msg = "Pass --gesture or enable interactive mode."
    raise typer.BadParameter(msg)


def _resolve_collection_type(
    *,
    collection_type: str,
    interactive: bool,
) -> str:
    """Validate the reserved collection_type input for session init."""
    del interactive
    if collection_type != collection_session.COLLECTION_TYPE_GESTURE:
        msg = (
            "Background collection_type session init is not implemented yet; "
            "use --collection-type gesture for now."
        )
        raise typer.BadParameter(msg)
    return collection_type


def _resolve_ports(
    *,
    cli_port: str | None,
    data_port: str | None,
    profile: collection_config.CollectionProfile,
    interactive: bool,
) -> tuple[str, str]:
    """Resolve CLI/Data ports from args, profile defaults, or interactive choice."""
    selected_cli_port = cli_port or profile.serial.cli_port
    selected_data_port = data_port or profile.serial.data_port
    if selected_cli_port is not None and selected_data_port is not None:
        return selected_cli_port, selected_data_port

    if not interactive:
        msg = "Pass both --cli-port and --data-port, or enable interactive mode."
        raise typer.BadParameter(msg)

    visible_ports = mmwave_ports.list_serial_ports()
    if not visible_ports:
        msg = "No visible serial ports were found."
        raise typer.BadParameter(msg)

    candidate_ports = mmwave_ports.list_candidate_mmwave_ports(visible_ports)
    candidate_devices = [port.device for port in candidate_ports or visible_ports]
    suggested_cli_port = selected_cli_port
    suggested_data_port = selected_data_port

    if candidate_ports:
        probe_results = mmwave_smoke_test.collect_probe_results(
            cli_baudrate=profile.serial.cli_baudrate,
            data_baudrate=profile.serial.data_baudrate,
            probe_duration_seconds=mmwave_smoke_test.DEFAULT_PROBE_DURATION_SECONDS,
            read_size=mmwave_smoke_test.DEFAULT_READ_SIZE,
            candidate_ports=candidate_ports,
        )
        probed_cli_port, probed_data_port = mmwave_smoke_test.infer_port_roles(
            probe_results,
        )
        suggested_cli_port = suggested_cli_port or probed_cli_port
        suggested_data_port = suggested_data_port or probed_data_port
        mmwave_ui.render_probe_results(
            console,
            probe_results,
            suggested_cli_port=probed_cli_port,
            suggested_data_port=probed_data_port,
        )

    resolved_cli_port = selected_cli_port or collection_ui.prompt_for_choice(
        message="Choose CLI port",
        choices=candidate_devices,
        default=suggested_cli_port,
    )
    data_choices = [port for port in candidate_devices if port != resolved_cli_port]
    if not data_choices:
        msg = "A separate data port is required, but only one candidate port was found."
        raise typer.BadParameter(msg)
    resolved_data_port = selected_data_port or collection_ui.prompt_for_choice(
        message="Choose Data port",
        choices=data_choices,
        default=suggested_data_port,
    )
    return resolved_cli_port, resolved_data_port


def _resolve_firmware_config_id(
    *,
    value: str | None,
    profile: collection_config.CollectionProfile,
    interactive: bool,
) -> str:
    """Resolve the mmWave cfg used by this session."""
    known_configs = mmwave_config.list_known_configs()
    known_config_ids = {config.config_id for config in known_configs}

    if value is not None:
        if value not in known_config_ids:
            msg = f"Unknown firmware config id: {value!r}."
            raise typer.BadParameter(msg)
        return value

    default_config_id = profile.default_firmware_config_id
    if not interactive or len(known_configs) <= 1:
        return default_config_id

    selected_config = mmwave_ui.prompt_for_known_config(
        known_configs,
        default_config_id=default_config_id,
        allow_skip=False,
        message="Choose firmware cfg for this session",
    )
    if selected_config is None:
        msg = "Firmware config selection was cancelled."
        raise typer.BadParameter(msg)
    return selected_config.config_id


def _resolve_choice(
    *,
    value: str | None,
    choices: tuple[str, ...],
    default: str | None,
    interactive: bool,
    message: str,
) -> str:
    """Resolve one choice field from args or interactive selection."""
    if value is not None:
        if value not in choices:
            msg = f"{value!r} is not valid for {message}."
            raise typer.BadParameter(msg)
        return value

    if interactive:
        return collection_ui.prompt_for_choice(
            message=message,
            choices=choices,
            default=default,
        )

    if default is not None:
        return default

    msg = f"Pass a value for {message} or enable interactive mode."
    raise typer.BadParameter(msg)


def _resolve_required_text(
    *,
    value: str | None,
    interactive: bool,
    message: str,
    default: str | None = None,
) -> str:
    """Resolve one required text field from args, prompt, or default."""
    if value is not None:
        stripped = value.strip()
        if stripped:
            return stripped
        msg = f"{message} cannot be empty."
        raise typer.BadParameter(msg)

    if interactive:
        return collection_ui.prompt_for_required_text(
            message=message,
            default=default,
        )

    if default is not None:
        return default

    msg = f"Pass --{message.replace('_', '-')} or enable interactive mode."
    raise typer.BadParameter(msg)


def _resolve_optional_text(
    *,
    value: str | None,
    interactive: bool,
    message: str,
) -> str | None:
    """Resolve one optional text field from args or prompt."""
    if value is not None:
        stripped = value.strip()
        return stripped or None

    if interactive:
        return collection_ui.prompt_for_optional_text(message=message)

    return None


def _resolve_optional_float(
    *,
    value: float | None,
    default: float | None,
    interactive: bool,
    message: str,
) -> float | None:
    """Resolve one optional float field from args or prompt."""
    if value is not None:
        return value

    if interactive:
        return collection_ui.prompt_for_optional_float(
            message=message,
            default=default,
        )

    return default
