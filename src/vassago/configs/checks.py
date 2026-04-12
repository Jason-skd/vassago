"""Pluggable repository config checks orchestrated by the validator runner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vassago.collection.rd import config as rd_config
from vassago.configs.metadata import HEADER_ONLY_KEYS
from vassago.configs.mmwave_cfg_integrity import validate_mmwave_cfg_integrity
from vassago.configs.models import ConfigKind
from vassago.configs.models import ConfigLifecycle
from vassago.configs.models import ValidationIssue
from vassago.configs.models import ValidationLevel
from vassago.configs.validation_contract import ValidationContext
from vassago.configs.validation_contract import ValidationMessage
from vassago.firmware.mmwave import config_validation as mmwave_config_validation

if TYPE_CHECKING:
    from pathlib import Path

    from vassago.configs.models import CatalogEntry


def run_entry_location_check(context: ValidationContext) -> list[ValidationMessage]:
    """Warn when lifecycle and directory role disagree."""
    messages: list[ValidationMessage] = []
    for entry in context.catalog.entries:
        path_text = entry.path.as_posix()
        if (
            entry.lifecycle == ConfigLifecycle.TEMPLATE
            and "/templates/" not in path_text
        ):
            messages.append(
                ValidationMessage(
                    level=ValidationLevel.WARN,
                    path=entry.path,
                    message=(
                        "Template lifecycle config should live under a templates "
                        "directory."
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


def run_mmwave_cfg_integrity_check(
    context: ValidationContext,
) -> list[ValidationMessage]:
    """Validate that managed mmWave cfg files still match the integrity registry."""
    mmwave_entries = context.catalog.list_entries(kind=ConfigKind.MMWAVE_CFG)
    return validate_mmwave_cfg_integrity(mmwave_entries)


def run_config_semantics_check(context: ValidationContext) -> list[ValidationMessage]:
    """Run per-entry semantic checks after discovery has built the catalog."""
    messages: list[ValidationMessage] = []
    for entry in context.catalog.entries:
        messages.extend(_validate_entry_semantics(entry, context=context))
    return messages


def _validate_entry_semantics(
    entry: CatalogEntry,
    *,
    context: ValidationContext,
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
            rd_config.load_collection_global_config(
                path=entry.path,
                catalog=context.catalog,
            )
        elif entry.kind == ConfigKind.COLLECTION_RD_PROFILE:
            rd_config.load_collection_profile(entry.path, catalog=context.catalog)
    except Exception as exc:  # noqa: BLE001
        messages.append(
            ValidationMessage(
                level=ValidationLevel.ERROR,
                path=entry.path,
                message=str(exc),
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


DEFAULT_CONFIG_VALIDATION_CHECKS = (
    run_entry_location_check,
    run_mmwave_cfg_integrity_check,
    run_config_semantics_check,
)
