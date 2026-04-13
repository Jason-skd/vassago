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

CONFIG_VALIDATION_PLUGIN_DISCOVERY = "catalog_discovery"
CONFIG_VALIDATION_PLUGIN_ENTRY_LOCATION = "entry_location"
CONFIG_VALIDATION_PLUGIN_SEMANTICS = "config_semantics"
CONFIG_VALIDATION_PLUGIN_MMWAVE_INTEGRITY = "mmwave_cfg_integrity"


@dataclass(slots=True, frozen=True)
class ValidationMessage:
    """One config validation result row."""

    level: ValidationLevel
    path: Path
    message: str
    plugin: str | None = None


@dataclass(slots=True, frozen=True)
class ValidationReport:
    """Aggregated messages from one or more config validation checks."""

    messages: tuple[ValidationMessage, ...]

    @property
    def has_errors(self) -> bool:
        """Return whether the report contains any blocking validation errors."""
        return any(message.level == ValidationLevel.ERROR for message in self.messages)

    def messages_for(
        self,
        *,
        level: ValidationLevel,
    ) -> tuple[ValidationMessage, ...]:
        """Return only the messages at one validation level."""
        return tuple(message for message in self.messages if message.level == level)

    @classmethod
    def empty(cls) -> ValidationReport:
        """Return an empty report when one stage has nothing to emit."""
        return cls(messages=())

    @classmethod
    def from_messages(
        cls,
        messages: Sequence[ValidationMessage],
    ) -> ValidationReport:
        """Build one report from a flat message sequence."""
        return cls(messages=tuple(messages))


@dataclass(slots=True, frozen=True)
class ValidationContext:
    """Shared validation context consumed by repository config checks."""

    catalog: ConfigCatalog


@dataclass(slots=True, frozen=True)
class ValidationRunResult:
    """Result of building the managed config catalog before peer checks run."""

    catalog: ConfigCatalog
    report: ValidationReport


def merge_reports(reports: Sequence[ValidationReport]) -> ValidationReport:
    """Merge multiple peer reports into one aggregate report."""
    return ValidationReport(
        messages=tuple(message for report in reports for message in report.messages)
    )


@runtime_checkable
class ConfigValidationCheck(Protocol):
    """Callable check used by the configs validation orchestrator."""

    def __call__(self, context: ValidationContext) -> ValidationReport:
        """Return one report for one config validation context."""
        ...
