"""Typer command registration for training workflows."""

from __future__ import annotations

import typer

from vassago.training.rd import cli as training_rd_cli


def register_commands(app: typer.Typer) -> None:
    """Attach training subcommands to an existing Typer app."""
    rd_app = typer.Typer(
        help="RD model training workflows.",
        no_args_is_help=True,
    )
    app.add_typer(rd_app, name="rd")
    training_rd_cli.register_commands(rd_app)

