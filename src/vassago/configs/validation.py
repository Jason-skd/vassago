"""Whole-repository managed config validation entrypoint."""

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
from vassago.configs.validation_contract import ConfigValidationCheck
from vassago.configs.validation_contract import ValidationContext
from vassago.configs.validation_contract import ValidationMessage

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Sequence
    from pathlib import Path


def validate_all_configs(
    *,
    checks: Sequence[ConfigValidationCheck] | None = None,
) -> list[ValidationMessage]:
    """Run metadata and kind-specific validation across the config tree."""
    clear_catalog_cache()
    clear_mmwave_cfg_integrity_cache()
    metadata_messages, catalog = _run_metadata_stage()
    _append_missing_mmwave_cfg_integrity_records(catalog)
    validation_context = ValidationContext(catalog=catalog)
    semantic_messages = _run_validation_checks(
        validation_context,
        checks=checks or DEFAULT_CONFIG_VALIDATION_CHECKS,
    )
    return [*metadata_messages, *semantic_messages]


def _run_metadata_stage() -> tuple[list[ValidationMessage], ConfigCatalog]:
    """Discover managed configs and validate metadata headers first."""
    try:
        root_specs = load_root_specs()
    except Exception as exc:  # noqa: BLE001
        return (
            [
                ValidationMessage(
                    level=ValidationLevel.ERROR,
                    path=resolve_repo_path(CATALOG_ROOTS_PATH),
                    message=str(exc),
                )
            ],
            ConfigCatalog(entries=()),
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
                )
                for entry in entries
            ]
        )

    valid_entries = [
        entry for entry in parsed_entries if entry.config_id not in duplicate_entries
    ]
    return messages, ConfigCatalog(entries=tuple(valid_entries))


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
) -> list[ValidationMessage]:
    """Run the selected peer checks against the discovered config catalog."""
    messages: list[ValidationMessage] = []
    for check in checks:
        messages.extend(check(context))
    return messages


def _append_missing_mmwave_cfg_integrity_records(catalog: ConfigCatalog) -> None:
    """Persist one first-seen digest for newly added managed mmWave cfg files."""
    mmwave_entries = catalog.list_entries(kind=ConfigKind.MMWAVE_CFG)
    if not mmwave_entries:
        return
    try:
        append_missing_mmwave_cfg_integrity_records(mmwave_entries)
    except Exception:  # noqa: BLE001
        return


def _print_messages(messages: Iterable[ValidationMessage]) -> int:
    """Render validation messages and return the error count."""
    error_count = 0
    for message in messages:
        print(
            f"{message.level} {to_repo_relative_path(message.path)}: {message.message}"
        )
        if message.level == ValidationLevel.ERROR:
            error_count += 1
    return error_count


def main() -> int:
    """Run the repository config validator as a module entrypoint."""
    messages = validate_all_configs()
    error_count = _print_messages(messages)
    if error_count:
        print(f"Config validation failed with {error_count} error(s).")
        return 1
    print("Config validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
