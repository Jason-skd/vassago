"""Shared model types for managed repository configs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from pathlib import Path


class ConfigKind(StrEnum):
    """Managed config kinds discovered from the repository config tree."""

    COLLECTION_RD_GLOBAL = "collection_rd_global"
    COLLECTION_RD_PROFILE = "collection_rd_profile"
    MMWAVE_CFG = "mmwave_cfg"


class ConfigLifecycle(StrEnum):
    """Lifecycle tags carried by repo-managed config metadata."""

    ACTIVE = "active"
    TEMPLATE = "template"


class ValidationLevel(StrEnum):
    """Validation severities used by repository config checks."""

    ERROR = "ERROR"
    WARN = "WARN"


@dataclass(slots=True, frozen=True)
class ConfigMetadata:
    """Normalized metadata parsed from one config file header."""

    kind: ConfigKind
    config_id: str
    label: str
    description: str
    lifecycle: ConfigLifecycle
    extras: dict[str, Any]


@dataclass(slots=True, frozen=True)
class CatalogEntry:
    """One discovered repository-managed config file."""

    metadata: ConfigMetadata
    path: Path

    @property
    def kind(self) -> ConfigKind:
        """Expose the metadata kind directly on the entry."""
        return self.metadata.kind

    @property
    def config_id(self) -> str:
        """Expose the config id directly on the entry."""
        return self.metadata.config_id

    @property
    def label(self) -> str:
        """Expose the label directly on the entry."""
        return self.metadata.label

    @property
    def description(self) -> str:
        """Expose the description directly on the entry."""
        return self.metadata.description

    @property
    def lifecycle(self) -> ConfigLifecycle:
        """Expose the lifecycle directly on the entry."""
        return self.metadata.lifecycle


@dataclass(slots=True, frozen=True)
class ValidationIssue:
    """One validation issue emitted by a kind-specific validator."""

    level: ValidationLevel
    message: str
