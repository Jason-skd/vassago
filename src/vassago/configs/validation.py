"""Whole-repository managed config validation entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vassago.collection.rd import config as rd_config
from vassago.configs.catalog import ConfigCatalog
from vassago.configs.catalog import clear_catalog_cache
from vassago.configs.catalog import discover_paths
from vassago.configs.catalog import load_root_specs
from vassago.configs.metadata import HEADER_ONLY_KEYS
from vassago.configs.metadata import parse_metadata_header
from vassago.configs.models import CatalogEntry
from vassago.configs.models import ConfigKind
from vassago.configs.models import ConfigLifecycle
from vassago.configs.models import ValidationIssue
from vassago.configs.models import ValidationLevel
from vassago.configs.paths import CATALOG_ROOTS_PATH
from vassago.configs.paths import resolve_repo_path
from vassago.configs.paths import to_repo_relative_path
from vassago.firmware.mmwave import config_validation as mmwave_config_validation

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


@dataclass(slots=True, frozen=True)
class ValidationMessage:
    """One config validation result row."""

    level: ValidationLevel
    path: Path
    message: str


def validate_all_configs() -> list[ValidationMessage]:
    """Run metadata and kind-specific validation across the config tree."""
    clear_catalog_cache()
    metadata_messages, catalog = _run_metadata_stage()
    semantic_messages = _run_semantic_stage(catalog=catalog)
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
    for entry in valid_entries:
        messages.extend(_validate_entry_location(entry))

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


def _run_semantic_stage(catalog: ConfigCatalog) -> list[ValidationMessage]:
    """Run per-kind semantic checks after metadata headers are valid."""
    messages: list[ValidationMessage] = []
    for entry in catalog.entries:
        messages.extend(_validate_entry_semantics(entry, catalog=catalog))
    return messages


def _validate_entry_semantics(
    entry: CatalogEntry,
    *,
    catalog: ConfigCatalog,
) -> list[ValidationMessage]:
    """Validate one discovered entry using shared and kind-specific checks."""
    messages = _validate_header_only_metadata_usage(entry)
    if any(message.level == ValidationLevel.ERROR for message in messages):
        return messages

    try:
        if entry.kind == ConfigKind.MMWAVE_CFG:
            messages.extend(
                _wrap_issues(
                    entry.path,
                    mmwave_config_validation.validate_cfg(
                        entry.path,
                        metadata=entry.metadata,
                    ),
                )
            )
        elif entry.kind == ConfigKind.COLLECTION_RD_GLOBAL:
            rd_config.load_collection_global_config(path=entry.path, catalog=catalog)
        elif entry.kind == ConfigKind.COLLECTION_RD_PROFILE:
            rd_config.load_collection_profile(entry.path, catalog=catalog)
    except Exception as exc:  # noqa: BLE001
        messages.append(
            ValidationMessage(
                level=ValidationLevel.ERROR,
                path=entry.path,
                message=str(exc),
            )
        )

    return messages


def _validate_entry_location(entry: CatalogEntry) -> list[ValidationMessage]:
    """Warn when lifecycle and directory role disagree."""
    path_text = entry.path.as_posix()
    messages: list[ValidationMessage] = []
    if entry.lifecycle == ConfigLifecycle.TEMPLATE and "/templates/" not in path_text:
        messages.append(
            ValidationMessage(
                level=ValidationLevel.WARN,
                path=entry.path,
                message=(
                    "Template lifecycle config should live under a templates directory."
                ),
            )
        )
    if entry.lifecycle == ConfigLifecycle.ACTIVE and "/templates/" in path_text:
        messages.append(
            ValidationMessage(
                level=ValidationLevel.WARN,
                path=entry.path,
                message=(
                    "Active lifecycle config should not live under a templates "
                    "directory."
                ),
            )
        )
    return messages


def _validate_header_only_metadata_usage(
    entry: CatalogEntry,
) -> list[ValidationMessage]:
    """Reject body keys that must live only in the structured header."""
    if entry.path.suffix != ".toml":
        return []

    try:
        data = rd_config.load_raw_toml(entry.path)
    except Exception as exc:  # noqa: BLE001
        return [
            ValidationMessage(
                level=ValidationLevel.ERROR,
                path=entry.path,
                message=str(exc),
            )
        ]

    invalid_keys = sorted(key for key in HEADER_ONLY_KEYS if key in data)
    if not invalid_keys:
        return []

    return [
        ValidationMessage(
            level=ValidationLevel.ERROR,
            path=entry.path,
            message=(
                "Header-only metadata keys must not appear in the TOML body: "
                f"{invalid_keys!r}"
            ),
        )
    ]


def _wrap_issues(path: Path, issues: list[ValidationIssue]) -> list[ValidationMessage]:
    """Attach the source path to kind-specific validation issues."""
    return [
        ValidationMessage(level=issue.level, path=path, message=issue.message)
        for issue in issues
    ]


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
