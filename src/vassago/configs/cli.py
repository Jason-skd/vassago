"""Typer command registration for repository-managed config tooling."""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING
from typing import Annotated

import typer
from rich.console import Console

from vassago.configs import checks as config_checks
from vassago.configs import ui as config_ui
from vassago.configs import validation as config_validation
from vassago.configs.mmwave_cfg_integrity import (
    append_missing_mmwave_cfg_integrity_records,
)
from vassago.configs.models import ConfigKind
from vassago.configs.models import ConfigLifecycle

if TYPE_CHECKING:
    from vassago.configs.validation_contract import ConfigValidationCheck
    from vassago.configs.validation_contract import ValidationReport

console = Console()


def register_commands(app: typer.Typer) -> None:
    """Attach config-management subcommands to an existing Typer app."""
    app.command("list")(handle_list)
    app.command("validate")(handle_validate)
    app.command("validate-discovery")(handle_validate_discovery)
    app.command("validate-entry-location")(handle_validate_entry_location)
    app.command("validate-semantics")(handle_validate_semantics)
    app.command("validate-mmwave-cfg-integrity")(handle_validate_mmwave_cfg_integrity)
    app.command("record-missing-mmwave-cfg-integrity")(
        handle_record_missing_mmwave_cfg_integrity
    )


def handle_list(
    kind: Annotated[
        ConfigKind | None,
        typer.Option(help="Optional config kind filter."),
    ] = None,
    lifecycle: Annotated[
        ConfigLifecycle | None,
        typer.Option(help="Optional lifecycle filter."),
    ] = None,
) -> None:
    """List discovered repository-managed configs from the catalog."""
    discovery_result = config_validation.run_config_discovery()
    if discovery_result.report.has_errors:
        _render_validation_report(
            report=discovery_result.report,
            title="Config Discovery Summary",
        )
        raise typer.Exit(code=1)

    entries = discovery_result.catalog.list_entries(kind=kind, lifecycle=lifecycle)
    config_ui.render_catalog_entries(console, entries)


def handle_validate(
    *,
    record_missing_mmwave_cfg_integrity: Annotated[
        bool,
        typer.Option(
            "--record-missing-mmwave-cfg-integrity/--no-record-missing-mmwave-cfg-integrity",
            help="Append missing mmWave cfg integrity records before validation.",
        ),
    ] = True,
) -> None:
    """Run whole-repository managed config validation."""
    _run_validation_command(
        title="Config Validation Summary",
        record_missing_mmwave_cfg_integrity=record_missing_mmwave_cfg_integrity,
    )


def handle_validate_discovery() -> None:
    """Validate discovery roots, metadata headers, kind matches, and duplicate ids."""
    discovery_result = config_validation.run_config_discovery()
    _render_validation_report(
        report=discovery_result.report,
        title="Config Discovery Summary",
    )
    raise typer.Exit(code=1 if discovery_result.report.has_errors else 0)


def handle_validate_entry_location() -> None:
    """Validate lifecycle and directory-role placement rules only."""
    _run_validation_command(
        title="Config Entry Location Summary",
        checks=(config_checks.run_entry_location_check,),
        record_missing_mmwave_cfg_integrity=False,
    )


def handle_validate_semantics() -> None:
    """Validate kind-specific TOML/cfg semantics after catalog discovery."""
    _run_validation_command(
        title="Config Semantics Summary",
        checks=(config_checks.run_config_semantics_check,),
        record_missing_mmwave_cfg_integrity=False,
    )


def handle_validate_mmwave_cfg_integrity() -> None:
    """Validate managed mmWave cfg digests against the integrity registry."""
    _run_validation_command(
        title="mmWave cfg Integrity Summary",
        checks=(config_checks.run_mmwave_cfg_integrity_check,),
        record_missing_mmwave_cfg_integrity=False,
    )


def handle_record_missing_mmwave_cfg_integrity(
    registry_path: Annotated[
        str | None,
        typer.Option(
            help="Optional output path for the integrity registry to update.",
        ),
    ] = None,
) -> None:
    """Append integrity hashes for newly added managed mmWave cfg ids only."""
    discovery_result = config_validation.run_config_discovery()
    if discovery_result.report.has_errors:
        _render_validation_report(
            report=discovery_result.report,
            title="Config Discovery Summary",
        )
        raise typer.Exit(code=1)

    mmwave_entries = discovery_result.catalog.list_entries(kind=ConfigKind.MMWAVE_CFG)
    resolved_registry_path = (
        pathlib.Path(registry_path) if registry_path is not None else None
    )
    written_path, added_config_ids = append_missing_mmwave_cfg_integrity_records(
        mmwave_entries,
        registry_path=resolved_registry_path,
    )
    console.print(f"Checked mmWave cfg integrity registry: {written_path}")
    if added_config_ids:
        console.print(f"added_config_ids: {', '.join(added_config_ids)}")
        return
    console.print("added_config_ids: none")


def _run_validation_command(
    *,
    title: str,
    checks: tuple[ConfigValidationCheck, ...] | None = None,
    record_missing_mmwave_cfg_integrity: bool,
) -> None:
    """Run one selected validation workflow and convert it to a CLI exit code."""
    report = config_validation.run_config_validation(
        checks=checks,
        record_missing_mmwave_cfg_integrity=record_missing_mmwave_cfg_integrity,
    )
    _render_validation_report(report=report, title=title)
    raise typer.Exit(code=1 if report.has_errors else 0)


def _render_validation_report(*, report: ValidationReport, title: str) -> None:
    """Render one validation report with the shared configs CLI style."""
    config_ui.render_validation_report(console, report=report, title=title)
