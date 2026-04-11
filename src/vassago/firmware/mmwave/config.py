"""Known cfg metadata used by the bring-up CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vassago.configs.catalog import load_catalog
from vassago.configs.models import CatalogEntry
from vassago.configs.models import ConfigKind
from vassago.configs.models import ConfigLifecycle

if TYPE_CHECKING:
    from pathlib import Path

    from vassago.configs.catalog import ConfigCatalog


@dataclass(slots=True, frozen=True)
class KnownMmwaveConfig:
    """One repository-managed cfg with user-facing metadata."""

    config_id: str
    path: Path
    label: str
    purpose: str
    risk: str
    recommended_for_bringup: bool


def list_known_configs(
    *,
    catalog: ConfigCatalog | None = None,
) -> list[KnownMmwaveConfig]:
    """Return active repository-managed cfgs exposed by the bring-up CLI."""
    resolved_catalog = catalog or load_catalog()
    configs = [
        _build_known_config(entry)
        for entry in resolved_catalog.list_entries(
            kind=ConfigKind.MMWAVE_CFG,
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    ]
    return sorted(
        configs,
        key=lambda config: (
            not config.recommended_for_bringup,
            config.label.lower(),
            config.config_id,
        ),
    )


def get_known_config(
    config_id: str,
    *,
    catalog: ConfigCatalog | None = None,
) -> KnownMmwaveConfig:
    """Resolve a managed cfg id to a CLI-facing config record."""
    resolved_catalog = catalog or load_catalog()
    entry = resolved_catalog.require_entry(
        kind=ConfigKind.MMWAVE_CFG,
        config_id=config_id,
    )
    if entry.lifecycle != ConfigLifecycle.ACTIVE:
        msg = f"mmWave cfg {config_id!r} is not active."
        raise KeyError(msg)
    return _build_known_config(entry)


def _build_known_config(entry: CatalogEntry) -> KnownMmwaveConfig:
    """Materialize one catalog entry into the bring-up config view."""
    risk = _require_extra_str(entry, "risk")
    recommended_for_bringup = _require_extra_bool(entry, "recommended_for_bringup")
    return KnownMmwaveConfig(
        config_id=entry.config_id,
        path=entry.path,
        label=entry.label,
        purpose=entry.description,
        risk=risk,
        recommended_for_bringup=recommended_for_bringup,
    )


def _require_extra_str(entry: CatalogEntry, key: str) -> str:
    """Require one non-empty string extra from config metadata."""
    value = entry.metadata.extras.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()

    msg = f"mmWave cfg {entry.config_id!r} is missing metadata extra {key!r}"
    raise ValueError(msg)


def _require_extra_bool(entry: CatalogEntry, key: str) -> bool:
    """Require one boolean extra from config metadata."""
    value = entry.metadata.extras.get(key)
    if isinstance(value, bool):
        return value

    msg = f"mmWave cfg {entry.config_id!r} is missing metadata extra {key!r}"
    raise ValueError(msg)
