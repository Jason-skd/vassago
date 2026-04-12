"""Shared contracts for orchestrated repository config validation checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Protocol
from typing import runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from vassago.configs.catalog import ConfigCatalog
    from vassago.configs.models import ValidationLevel


@dataclass(slots=True, frozen=True)
class ValidationMessage:
    """One config validation result row."""

    level: ValidationLevel
    path: Path
    message: str


@dataclass(slots=True, frozen=True)
class ValidationContext:
    """Shared validation context consumed by repository config checks."""

    catalog: ConfigCatalog


@runtime_checkable
class ConfigValidationCheck(Protocol):
    """Callable check used by the configs validation orchestrator."""

    def __call__(self, context: ValidationContext) -> Sequence[ValidationMessage]:
        """Return zero or more validation messages for one config catalog."""
        ...
