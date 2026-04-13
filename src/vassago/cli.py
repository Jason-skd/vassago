"""Top-level Typer application for Vassago workflows."""

from __future__ import annotations

import typer

from vassago.collection.rd import cli as collection_rd_cli
from vassago.configs import cli as configs_cli
from vassago.firmware.mmwave import cli as mmwave_cli

app = typer.Typer(
    add_completion=False,
    help=(
        "Unified command entry for firmware bring-up, dataset collection, "
        "and future Vassago workflows."
    ),
    no_args_is_help=True,
)

firmware_app = typer.Typer(
    help="Firmware bring-up and hardware validation workflows.",
    no_args_is_help=True,
)
app.add_typer(firmware_app, name="firmware")

collection_app = typer.Typer(
    help="Dataset collection workflows.",
    no_args_is_help=True,
)
app.add_typer(collection_app, name="collection")

configs_app = typer.Typer(
    help="Repository-managed config tooling.",
    no_args_is_help=True,
)
app.add_typer(configs_app, name="configs")
configs_cli.register_commands(configs_app)

mmwave_app = typer.Typer(
    help="TI-style mmWave UART tooling.",
    no_args_is_help=True,
)
firmware_app.add_typer(mmwave_app, name="mmwave")
mmwave_cli.register_commands(mmwave_app)

collection_rd_app = typer.Typer(
    help="RD dataset collection workflows.",
    no_args_is_help=True,
)
collection_app.add_typer(collection_rd_app, name="rd")
collection_rd_cli.register_commands(collection_rd_app)


def run() -> None:
    """Run the Typer application."""
    app()
