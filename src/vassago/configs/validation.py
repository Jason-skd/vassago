"""Whole-repository managed config validation orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vassago.configs.catalog import ConfigCatalog
from vassago.configs.catalog import clear_catalog_cache
from vassago.configs.catalog import discover_paths
from vassago.configs.catalog import load_root_specs
from vassago.configs.checks import DEFAULT_CONFIG_VALIDATION_CHECKS
from vassago.configs.metadata import parse_metadata_header
from vassago.configs.mmwave_cfg_integrity import (
    append_missing_mmwave_cfg_integrity_records,
)
from vassago.configs.mmwave_cfg_integrity import clear_mmwave_cfg_integrity_cache
from vassago.configs.models import CatalogEntry
from vassago.configs.models import ConfigKind
from vassago.configs.models import ValidationLevel
from vassago.configs.paths import CATALOG_ROOTS_PATH
from vassago.configs.paths import resolve_repo_path
from vassago.configs.paths import to_repo_relative_path
from vassago.configs.validation_contract import CONFIG_VALIDATION_PLUGIN_DISCOVERY
from vassago.configs.validation_contract import ConfigValidationCheck
from vassago.configs.validation_contract import ValidationContext
from vassago.configs.validation_contract import ValidationMessage
from vassago.configs.validation_contract import ValidationReport
from vassago.configs.validation_contract import ValidationRunResult
from vassago.configs.validation_contract import merge_reports

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def run_config_validation(
    *,
    checks: Sequence[ConfigValidationCheck] | None = None,
    record_missing_mmwave_cfg_integrity: bool = True,
) -> ValidationReport:
    """Run discovery and the selected peer checks across the config tree."""
    discovery_result = run_config_discovery()
    if discovery_result.report.has_errors:
        return discovery_result.report

    if record_missing_mmwave_cfg_integrity:
        _append_missing_mmwave_cfg_integrity_records(discovery_result.catalog)

    validation_report = run_config_validation_context(
        context=ValidationContext(catalog=discovery_result.catalog),
        checks=checks,
    )
    return merge_reports((discovery_result.report, validation_report))


def run_config_validation_context(
    *,
    context: ValidationContext,
    checks: Sequence[ConfigValidationCheck] | None = None,
) -> ValidationReport:
    """Run the selected peer checks for one already-built validation context."""
    return _run_validation_checks(
        context,
        checks=checks or DEFAULT_CONFIG_VALIDATION_CHECKS,
    )


def validate_all_configs(
    *,
    checks: Sequence[ConfigValidationCheck] | None = None,
) -> list[ValidationMessage]:
    """Return the flat config validation messages for compatibility callers."""
    return list(run_config_validation(checks=checks).messages)


def run_config_discovery() -> ValidationRunResult:
    """Discover managed configs and validate metadata before peer checks run."""
    clear_catalog_cache()
    clear_mmwave_cfg_integrity_cache()

    try:
        root_specs = load_root_specs()
    except Exception as exc:  # noqa: BLE001
        return ValidationRunResult(
            catalog=ConfigCatalog(entries=()),
            report=ValidationReport.from_messages(
                [
                    ValidationMessage(
                        level=ValidationLevel.ERROR,
                        path=resolve_repo_path(CATALOG_ROOTS_PATH),
                        message=str(exc),
                        plugin=CONFIG_VALIDATION_PLUGIN_DISCOVERY,
                    )
                ]
            ),
        )

    messages: list[ValidationMessage] = []
    seen_paths: set[Path] = set()
    parsed_entries: list[CatalogEntry] = []

    for root_spec in root_specs:
        for path in sorted(discover_paths(root_spec)):
            if path in seen_paths:
                continue
            seen_paths.add(path)
            messages.extend(
                _parse_entry_metadata(
                    path=path,
                    expected_kind=root_spec.kind,
                    parsed_entries=parsed_entries,
                )
            )

    duplicate_entries = _find_duplicate_ids(parsed_entries)
    for config_id, entries in duplicate_entries.items():
        joined_paths = ", ".join(to_repo_relative_path(entry.path) for entry in entries)
        messages.extend(
            [
                ValidationMessage(
                    level=ValidationLevel.ERROR,
                    path=entry.path,
                    message=(
                        f"Duplicate config_id {config_id!r} detected across "
                        f"{joined_paths}."
                    ),
                    plugin=CONFIG_VALIDATION_PLUGIN_DISCOVERY,
                )
                for entry in entries
            ]
        )

    valid_entries = [
        entry for entry in parsed_entries if entry.config_id not in duplicate_entries
    ]
    return ValidationRunResult(
        catalog=ConfigCatalog(entries=tuple(valid_entries)),
        report=ValidationReport.from_messages(messages),
    )


def _parse_entry_metadata(
    *,
    path: Path,
    expected_kind: ConfigKind,
    parsed_entries: list[CatalogEntry],
) -> list[ValidationMessage]:
    """Parse one metadata header and reject kind mismatches."""
    try:
        metadata = parse_metadata_header(path)
    except Exception as exc:  # noqa: BLE001
        return [
            ValidationMessage(
                level=ValidationLevel.ERROR,
                path=path,
                message=str(exc),
                plugin=CONFIG_VALIDATION_PLUGIN_DISCOVERY,
            )
        ]

    if metadata.kind != expected_kind:
        return [
            ValidationMessage(
                level=ValidationLevel.ERROR,
                path=path,
                message=(
                    f"Config kind mismatch: header={metadata.kind.value}, "
                    f"root={expected_kind.value}."
                ),
                plugin=CONFIG_VALIDATION_PLUGIN_DISCOVERY,
            )
        ]

    parsed_entries.append(CatalogEntry(metadata=metadata, path=path))
    return []


def _find_duplicate_ids(
    entries: list[CatalogEntry],
) -> dict[str, list[CatalogEntry]]:
    """Group duplicated config ids across the managed config tree."""
    grouped_entries: dict[str, list[CatalogEntry]] = {}
    for entry in entries:
        grouped_entries.setdefault(entry.config_id, []).append(entry)
    return {
        config_id: grouped
        for config_id, grouped in grouped_entries.items()
        if len(grouped) > 1
    }


def _run_validation_checks(
    context: ValidationContext,
    *,
    checks: Sequence[ConfigValidationCheck],
) -> ValidationReport:
    """Run the selected peer checks against the discovered config catalog."""
    reports = tuple(check(context) for check in checks)
    return merge_reports(reports)


def _append_missing_mmwave_cfg_integrity_records(catalog: ConfigCatalog) -> None:
    """Persist one first-seen digest for newly added managed mmWave cfg files."""
    mmwave_entries = catalog.list_entries(kind=ConfigKind.MMWAVE_CFG)
    if not mmwave_entries:
        return
    try:
        append_missing_mmwave_cfg_integrity_records(mmwave_entries)
    except Exception:  # noqa: BLE001
        return


def _print_report(report: ValidationReport) -> int:
    """Render a flat validation report and return the error count."""
    error_count = len(report.messages_for(level=ValidationLevel.ERROR))
    warn_count = len(report.messages_for(level=ValidationLevel.WARN))
    result = "fail" if error_count else "pass_with_warnings" if warn_count else "pass"

    print("Config Validation Summary")
    print(f"result: {result}")
    print(f"errors: {error_count}")
    print(f"warnings: {warn_count}")
    for message in report.messages:
        plugin_text = f"{message.plugin} " if message.plugin else ""
        print(
            f"[{message.level}] {plugin_text}"
            f"{to_repo_relative_path(message.path)}: {message.message}"
        )
    return error_count


def main() -> int:
    """Run the repository config validator as a module entrypoint."""
    report = run_config_validation()
    error_count = _print_report(report)
    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
