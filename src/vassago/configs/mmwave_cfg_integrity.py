"""Integrity registry support for repository-managed mmWave cfg files."""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from vassago.configs.models import ValidationLevel
from vassago.configs.paths import MMWAVE_CFG_INTEGRITY_PATH
from vassago.configs.paths import resolve_repo_path
from vassago.configs.validation_contract import ValidationMessage

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from vassago.configs.models import CatalogEntry

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(slots=True, frozen=True)
class MmwaveCfgIntegrityRecord:
    """One integrity baseline row for a managed mmWave cfg."""

    config_id: str
    sha256: str


@lru_cache
def load_mmwave_cfg_integrity_registry(
    registry_path: Path | None = None,
) -> dict[str, MmwaveCfgIntegrityRecord]:
    """Load the expected content digests for managed mmWave cfg files."""
    resolved_registry_path = resolve_repo_path(
        registry_path or MMWAVE_CFG_INTEGRITY_PATH,
    )
    with resolved_registry_path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        msg = (
            "mmWave cfg integrity registry must parse to a TOML table: "
            f"{resolved_registry_path}"
        )
        raise TypeError(msg)

    raw_entries = data.get("cfg")
    if not isinstance(raw_entries, list) or not raw_entries:
        msg = (
            "mmWave cfg integrity registry must define a non-empty [[cfg]] array: "
            f"{resolved_registry_path}"
        )
        raise ValueError(msg)

    records: dict[str, MmwaveCfgIntegrityRecord] = {}
    for raw_entry in raw_entries:
        record = _parse_integrity_record(
            raw_entry,
            registry_path=resolved_registry_path,
        )
        if record.config_id in records:
            msg = (
                "mmWave cfg integrity registry contains duplicate config_id "
                f"{record.config_id!r}: {resolved_registry_path}"
            )
            raise ValueError(msg)
        records[record.config_id] = record
    return records


def clear_mmwave_cfg_integrity_cache() -> None:
    """Clear the cached mmWave cfg integrity registry."""
    load_mmwave_cfg_integrity_registry.cache_clear()


def compute_mmwave_cfg_digest(path: Path) -> str:
    """Compute a path-independent normalized content digest for one cfg file."""
    normalized_text = _normalize_cfg_text(path.read_text(encoding="utf-8"))
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def validate_mmwave_cfg_integrity(
    entries: Iterable[CatalogEntry],
    *,
    registry_path: Path | None = None,
) -> list[ValidationMessage]:
    """Validate that each managed cfg still matches its recorded content digest."""
    entry_list = list(entries)
    if not entry_list:
        return []

    resolved_registry_path = resolve_repo_path(
        registry_path or MMWAVE_CFG_INTEGRITY_PATH,
    )
    try:
        registry = load_mmwave_cfg_integrity_registry(registry_path)
    except Exception as exc:  # noqa: BLE001
        return [
            ValidationMessage(
                level=ValidationLevel.ERROR,
                path=resolved_registry_path,
                message=str(exc),
            )
        ]

    messages: list[ValidationMessage] = []
    entries_by_id = {entry.config_id: entry for entry in entry_list}

    missing_ids = sorted(set(entries_by_id) - set(registry))
    messages.extend(
        ValidationMessage(
            level=ValidationLevel.ERROR,
            path=entries_by_id[config_id].path,
            message=(
                f"mmWave cfg integrity registry is missing config_id {config_id!r}."
            ),
        )
        for config_id in missing_ids
    )

    unknown_ids = sorted(set(registry) - set(entries_by_id))
    messages.extend(
        ValidationMessage(
            level=ValidationLevel.ERROR,
            path=resolved_registry_path,
            message=(
                "mmWave cfg integrity registry declares unknown config_id "
                f"{config_id!r}."
            ),
        )
        for config_id in unknown_ids
    )

    shared_ids = sorted(set(entries_by_id) & set(registry))
    for config_id in shared_ids:
        entry = entries_by_id[config_id]
        expected_digest = registry[config_id].sha256
        actual_digest = compute_mmwave_cfg_digest(entry.path)
        if actual_digest == expected_digest:
            continue
        messages.append(
            ValidationMessage(
                level=ValidationLevel.ERROR,
                path=entry.path,
                message=(
                    "mmWave cfg content digest mismatch for "
                    f"{config_id!r}: expected {expected_digest}, got "
                    f"{actual_digest}. This cfg may be migrated to another path, "
                    "but its content must not change."
                ),
            )
        )

    return messages


def _parse_integrity_record(
    raw_entry: object,
    *,
    registry_path: Path,
) -> MmwaveCfgIntegrityRecord:
    """Parse one [[cfg]] integrity table."""
    if not isinstance(raw_entry, dict):
        msg = f"Integrity registry entries must be tables: {registry_path}"
        raise TypeError(msg)

    config_id = _require_non_empty_str(
        raw_entry.get("config_id"),
        field_name="config_id",
        registry_path=registry_path,
    )
    sha256 = _require_sha256(
        raw_entry.get("sha256"),
        registry_path=registry_path,
        config_id=config_id,
    )
    return MmwaveCfgIntegrityRecord(config_id=config_id, sha256=sha256)


def _normalize_cfg_text(text: str) -> str:
    """Normalize line endings so digest checks stay portable across platforms."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _require_non_empty_str(
    value: object,
    *,
    field_name: str,
    registry_path: Path,
) -> str:
    """Require one non-empty string field from the integrity registry."""
    if isinstance(value, str) and value.strip():
        return value.strip()

    msg = f"Integrity registry is missing string field {field_name!r}: {registry_path}"
    raise ValueError(msg)


def _require_sha256(
    value: object,
    *,
    registry_path: Path,
    config_id: str,
) -> str:
    """Require one lowercase hex SHA-256 digest from the integrity registry."""
    sha256 = _require_non_empty_str(
        value,
        field_name="sha256",
        registry_path=registry_path,
    )
    if SHA256_PATTERN.fullmatch(sha256):
        return sha256

    msg = (
        f"Integrity registry sha256 for {config_id!r} must be 64 lowercase hex "
        f"characters: {registry_path}"
    )
    raise ValueError(msg)
