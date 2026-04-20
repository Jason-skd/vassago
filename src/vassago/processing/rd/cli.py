"""Typer command registration for RD processing workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from vassago.processing.rd import artifact as rd_artifact

console = Console()


def register_commands(app: typer.Typer) -> None:
    """Attach RD processing subcommands to an existing Typer app."""
    app.command("extract")(handle_extract)


def handle_extract(
    manifest: Annotated[
        Path,
        typer.Option(help="Path to one collection session manifest.json."),
    ],
    take_id: Annotated[
        str | None,
        typer.Option(help="Extract only one accepted take_id from the manifest."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            help="Explicit rd.npz output path. Requires --take-id.",
        ),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite/--no-overwrite",
            help="Overwrite rd.npz when it already exists.",
        ),
    ] = False,
) -> None:
    """Extract canonical rd.npz artifacts from one collection manifest."""
    try:
        output_paths = rd_artifact.extract_manifest_samples(
            manifest_path=manifest,
            take_id=take_id,
            output_path=output,
            overwrite=overwrite,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if not output_paths:
        console.print("No accepted takes with raw_uart.bin were found in the manifest.")
        raise typer.Exit(code=1)

    console.print("RD extract summary")
    console.print(f"manifest: {manifest.expanduser().resolve()}")
    console.print(f"written_artifacts: {len(output_paths)}")
    for written_path in output_paths:
        console.print(f"output: {written_path}")
