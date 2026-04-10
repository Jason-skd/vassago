"""Top-level Typer application for Vassago workflows."""

from __future__ import annotations

import typer

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

mmwave_app = typer.Typer(
    help="TI-style mmWave UART tooling.",
    no_args_is_help=True,
)
firmware_app.add_typer(mmwave_app, name="mmwave")
mmwave_cli.register_commands(mmwave_app)


def run() -> None:
    """Run the Typer application."""
    app()
