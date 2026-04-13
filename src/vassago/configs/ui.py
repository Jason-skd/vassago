"""Rich rendering helpers for config catalog and validation commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table

from vassago.configs.models import ValidationLevel
from vassago.configs.paths import to_repo_relative_path

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rich.console import Console

    from vassago.configs.models import CatalogEntry
    from vassago.configs.validation_contract import ValidationReport


def render_catalog_entries(
    console: Console,
    entries: Sequence[CatalogEntry],
) -> None:
    """Render the discovered managed config catalog as a compact table."""
    table = Table(title="Managed Config Catalog")
    table.add_column("config_id")
    table.add_column("kind")
    table.add_column("lifecycle")
    table.add_column("path")

    for entry in sorted(entries, key=lambda item: (item.kind.value, item.config_id)):
        table.add_row(
            entry.config_id,
            entry.kind.value,
            entry.lifecycle.value,
            to_repo_relative_path(entry.path),
        )

    if not entries:
        table.add_row("-", "-", "-", "No managed configs discovered.")

    console.print(table)


def render_validation_report(
    console: Console,
    *,
    report: ValidationReport,
    title: str = "Config Validation Summary",
) -> None:
    """Render one config validation report in a CLI-friendly summary form."""
    error_count = len(report.messages_for(level=ValidationLevel.ERROR))
    warn_count = len(report.messages_for(level=ValidationLevel.WARN))
    result = "fail" if error_count else "pass_with_warnings" if warn_count else "pass"

    console.print(title)
    console.print(f"result: {result}")
    console.print(f"errors: {error_count}")
    console.print(f"warnings: {warn_count}")

    for message in report.messages:
        header = f"[{message.level}]"
        if message.plugin is not None:
            header = f"{header} {message.plugin}"
        console.print(f"{header} {to_repo_relative_path(message.path)}")
        console.print(f"  {message.message}")
