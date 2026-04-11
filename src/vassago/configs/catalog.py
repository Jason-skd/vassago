"""Repository-managed config discovery and lookup helpers."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from vassago.configs.metadata import parse_metadata_header
from vassago.configs.models import CatalogEntry
from vassago.configs.models import ConfigKind
from vassago.configs.models import ConfigLifecycle
from vassago.configs.paths import CATALOG_ROOTS_PATH
from vassago.configs.paths import resolve_repo_path
from vassago.configs.paths import to_repo_relative_path

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(slots=True, frozen=True)
class RootSpec:
    """One discovery rule loaded from the catalog roots registry."""

    kind: ConfigKind
    glob: str


@dataclass(slots=True, frozen=True)
class ConfigCatalog:
    """In-memory index of all discovered repository-managed configs."""

    entries: tuple[CatalogEntry, ...]

    def list_entries(
        self,
        *,
        kind: ConfigKind | None = None,
        lifecycle: ConfigLifecycle | None = None,
    ) -> list[CatalogEntry]:
        """List discovered entries filtered by kind and/or lifecycle."""
        return [
            entry
            for entry in self.entries
            if (kind is None or entry.kind == kind)
            and (lifecycle is None or entry.lifecycle == lifecycle)
        ]

    def require_entry(self, *, kind: ConfigKind, config_id: str) -> CatalogEntry:
        """Resolve one entry by kind and config id."""
        for entry in self.entries:
            if entry.kind == kind and entry.config_id == config_id:
                return entry

        msg = f"Unknown {kind.value} config id: {config_id}"
        raise KeyError(msg)

    def require_single_active(self, *, kind: ConfigKind) -> CatalogEntry:
        """Resolve the single active entry for one kind."""
        active_entries = self.list_entries(kind=kind, lifecycle=ConfigLifecycle.ACTIVE)
        if len(active_entries) == 1:
            return active_entries[0]

        msg = (
            f"Expected exactly one active {kind.value} entry, found "
            f"{len(active_entries)}"
        )
        raise ValueError(msg)


@lru_cache
def load_catalog() -> ConfigCatalog:
    """Discover all repository-managed configs and build the catalog."""
    root_specs = load_root_specs()
    entries: list[CatalogEntry] = []
    seen_paths: set[Path] = set()
    seen_ids: dict[str, Path] = {}

    for root_spec in root_specs:
        for path in sorted(discover_paths(root_spec)):
            if path in seen_paths:
                continue
            seen_paths.add(path)

            metadata = parse_metadata_header(path)
            if metadata.kind != root_spec.kind:
                msg = (
                    f"Config kind mismatch in {to_repo_relative_path(path)}: "
                    f"header={metadata.kind.value}, root={root_spec.kind.value}"
                )
                raise ValueError(msg)

            existing_path = seen_ids.get(metadata.config_id)
            if existing_path is not None:
                msg = (
                    f"Duplicate config id {metadata.config_id!r} in "
                    f"{to_repo_relative_path(existing_path)} and "
                    f"{to_repo_relative_path(path)}"
                )
                raise ValueError(msg)
            seen_ids[metadata.config_id] = path

            entries.append(CatalogEntry(metadata=metadata, path=path))

    return ConfigCatalog(entries=tuple(entries))


def clear_catalog_cache() -> None:
    """Clear the cached repository config catalog."""
    load_catalog.cache_clear()


def load_root_specs() -> tuple[RootSpec, ...]:
    """Load discovery roots from the registry config."""
    registry_path = resolve_repo_path(CATALOG_ROOTS_PATH)
    with registry_path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        msg = f"Catalog roots file must parse to a TOML table: {registry_path}"
        raise TypeError(msg)

    raw_roots = data.get("root")
    if not isinstance(raw_roots, list) or not raw_roots:
        msg = (
            "Catalog roots file must define a non-empty [[root]] array: "
            f"{registry_path}"
        )
        raise ValueError(msg)

    return tuple(
        _parse_root_spec(item, registry_path=registry_path) for item in raw_roots
    )


def _parse_root_spec(
    item: object,
    *,
    registry_path: Path,
) -> RootSpec:
    """Parse one root spec table from the registry file."""
    if not isinstance(item, dict):
        msg = f"Catalog root entries must be tables: {registry_path}"
        raise TypeError(msg)

    kind_value = item.get("kind")
    glob_value = item.get("glob")
    if not isinstance(kind_value, str) or not kind_value.strip():
        msg = f"Catalog root is missing kind in {registry_path}"
        raise ValueError(msg)
    if not isinstance(glob_value, str) or not glob_value.strip():
        msg = f"Catalog root is missing glob in {registry_path}"
        raise ValueError(msg)

    return RootSpec(
        kind=ConfigKind(kind_value.strip()),
        glob=glob_value.strip(),
    )


def discover_paths(root_spec: RootSpec) -> list[Path]:
    """Discover file paths for one configured root glob."""
    repository_root = resolve_repo_path(".")
    return [
        path.resolve()
        for path in repository_root.glob(root_spec.glob)
        if path.is_file()
    ]
