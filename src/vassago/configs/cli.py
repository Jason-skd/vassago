"""Typer command registration for repository-managed config tooling."""

from __future__ import annotations

import pathlib
from typing import Annotated

import typer

from vassago.configs import load_catalog
from vassago.configs.mmwave_cfg_integrity import (
    append_missing_mmwave_cfg_integrity_records,
)
from vassago.configs.models import ConfigKind


def register_commands(app: typer.Typer) -> None:
    """Attach config-management subcommands to an existing Typer app."""
    app.command("record-missing-mmwave-cfg-integrity")(
        handle_record_missing_mmwave_cfg_integrity
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
    catalog = load_catalog()
    mmwave_entries = catalog.list_entries(kind=ConfigKind.MMWAVE_CFG)
    resolved_registry_path = (
        pathlib.Path(registry_path) if registry_path is not None else None
    )
    written_path, added_config_ids = append_missing_mmwave_cfg_integrity_records(
        mmwave_entries,
        registry_path=resolved_registry_path,
    )
    print(f"Checked mmWave cfg integrity registry: {written_path}")
    if added_config_ids:
        print(f"added_config_ids: {', '.join(added_config_ids)}")
        return
    print("added_config_ids: none")
