"""Typer command registration for offline processing workflows."""

from __future__ import annotations

import typer

from vassago.processing.rd import cli as processing_rd_cli


def register_commands(app: typer.Typer) -> None:
    """Attach processing subcommands to an existing Typer app."""
    rd_app = typer.Typer(
        help="RD offline artifact generation workflows.",
        no_args_is_help=True,
    )
    app.add_typer(rd_app, name="rd")
    processing_rd_cli.register_commands(rd_app)
