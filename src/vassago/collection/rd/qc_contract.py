"""Shared QC contracts for live collection and future offline validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Literal
from typing import Protocol
from typing import runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from vassago.collection.rd.config import WindowRange
    from vassago.firmware.mmwave.protocol import SmokeTestSummary

type QcSeverity = Literal["error", "warn", "info"]

QC_SEVERITY_ERROR: QcSeverity = "error"
QC_SEVERITY_WARN: QcSeverity = "warn"
QC_SEVERITY_INFO: QcSeverity = "info"

QC_PLUGIN_QUICK = "quick_qc"
QC_PLUGIN_METADATA = "metadata_qc"
QC_PLUGIN_AI_PRECHECK = "ai_precheck"

MANIFEST_TOP_LEVEL_EXTRACT_FIELDS = (
    "schema_version",
    "session_id",
    "subject_name",
    "hand",
    "distance_m",
    "angle_deg",
    "environment",
    "operator_name",
    "note",
    "radar_id",
    "firmware_id",
    "gesture",
    "batch_size",
    "gesture_options",
    "environment_options",
    "cli_port",
    "data_port",
    "data_baudrate",
    "takes",
)

MANIFEST_TOP_LEVEL_SELECTION_FIELDS = (
    "hand",
    "distance_m",
    "angle_deg",
    "environment",
    "radar_id",
    "firmware_id",
    "gesture",
)

MANIFEST_TOP_LEVEL_OPTION_FIELDS = (
    "gesture_options",
    "environment_options",
)

MANIFEST_TAKE_EXTRACT_FIELDS = (
    "take_index",
    "take_id",
    "status",
    "raw_uart_path",
    "accepted_at",
    "capture_window",
    "target_window",
    "marked_window",
)


@dataclass(slots=True, frozen=True)
class SnapshotComparisonRule:
    """Describe how one top-level manifest field is checked against a snapshot."""

    top_level_field: str
    snapshot_path: tuple[str, ...]
    mismatch_severity: QcSeverity
    rationale: str


@dataclass(slots=True, frozen=True)
class SnapshotMembershipRule:
    """Describe how one top-level field must belong to a snapshot collection."""

    top_level_field: str
    snapshot_path: tuple[str, ...]
    violation_severity: QcSeverity
    rationale: str


MANIFEST_SNAPSHOT_COMPARISON_RULES = (
    SnapshotComparisonRule(
        top_level_field="batch_size",
        snapshot_path=("batch_size",),
        mismatch_severity=QC_SEVERITY_ERROR,
        rationale=(
            "batch_size is part of the top-level public contract and must mirror "
            "the config snapshot exactly."
        ),
    ),
    SnapshotComparisonRule(
        top_level_field="gesture_options",
        snapshot_path=("options", "gestures"),
        mismatch_severity=QC_SEVERITY_ERROR,
        rationale=(
            "gesture_options is part of the top-level public contract and must "
            "mirror the config snapshot exactly."
        ),
    ),
    SnapshotComparisonRule(
        top_level_field="environment_options",
        snapshot_path=("options", "environments"),
        mismatch_severity=QC_SEVERITY_ERROR,
        rationale=(
            "environment_options is part of the top-level public contract and "
            "must mirror the config snapshot exactly."
        ),
    ),
    SnapshotComparisonRule(
        top_level_field="hand",
        snapshot_path=("defaults", "hand"),
        mismatch_severity=QC_SEVERITY_WARN,
        rationale=(
            "hand is operator-selected at session init, but the snapshot default "
            "still provides the provenance baseline."
        ),
    ),
    SnapshotComparisonRule(
        top_level_field="distance_m",
        snapshot_path=("defaults", "distance_m"),
        mismatch_severity=QC_SEVERITY_WARN,
        rationale=(
            "distance_m is operator-selected at session init, but the snapshot "
            "default still provides the provenance baseline."
        ),
    ),
    SnapshotComparisonRule(
        top_level_field="angle_deg",
        snapshot_path=("defaults", "angle_deg"),
        mismatch_severity=QC_SEVERITY_WARN,
        rationale=(
            "angle_deg is operator-selected at session init, but the snapshot "
            "default still provides the provenance baseline."
        ),
    ),
    SnapshotComparisonRule(
        top_level_field="environment",
        snapshot_path=("defaults", "environment"),
        mismatch_severity=QC_SEVERITY_WARN,
        rationale=(
            "environment is operator-selected at session init, but the snapshot "
            "default still provides the provenance baseline."
        ),
    ),
    SnapshotComparisonRule(
        top_level_field="radar_id",
        snapshot_path=("defaults", "radar_id"),
        mismatch_severity=QC_SEVERITY_WARN,
        rationale=(
            "radar_id is operator-selected at session init, but the snapshot "
            "default still provides the provenance baseline."
        ),
    ),
    SnapshotComparisonRule(
        top_level_field="firmware_id",
        snapshot_path=("defaults", "firmware_id"),
        mismatch_severity=QC_SEVERITY_WARN,
        rationale=(
            "firmware_id is a human-readable session label that may override the "
            "snapshot default, but mismatches should still be surfaced."
        ),
    ),
    SnapshotComparisonRule(
        top_level_field="data_baudrate",
        snapshot_path=("serial", "data_baudrate"),
        mismatch_severity=QC_SEVERITY_WARN,
        rationale=(
            "data_baudrate is part of the extractor-facing top-level contract and "
            "may override the config default for one session."
        ),
    ),
)

MANIFEST_SNAPSHOT_MEMBERSHIP_RULES = (
    SnapshotMembershipRule(
        top_level_field="gesture",
        snapshot_path=("options", "gestures"),
        violation_severity=QC_SEVERITY_ERROR,
        rationale="gesture must remain inside the snapshot-defined choice set.",
    ),
    SnapshotMembershipRule(
        top_level_field="environment",
        snapshot_path=("options", "environments"),
        violation_severity=QC_SEVERITY_ERROR,
        rationale="environment must remain inside the snapshot-defined choice set.",
    ),
)


@dataclass(slots=True, frozen=True)
class QcFinding:
    """One QC finding emitted by a live or offline check."""

    plugin: str
    severity: QcSeverity
    code: str
    message: str
    field_path: str | None = None
    take_id: str | None = None


@dataclass(slots=True, frozen=True)
class QcReport:
    """Aggregated QC findings from one or more peer checks."""

    findings: tuple[QcFinding, ...]

    @property
    def has_errors(self) -> bool:
        """Return whether the report contains any blocking finding."""
        return any(finding.severity == QC_SEVERITY_ERROR for finding in self.findings)

    def findings_for(self, *, severity: QcSeverity) -> tuple[QcFinding, ...]:
        """Return only findings at one severity level."""
        return tuple(
            finding for finding in self.findings if finding.severity == severity
        )

    @classmethod
    def empty(cls) -> QcReport:
        """Return an empty report for callers that have nothing to emit."""
        return cls(findings=())

    @classmethod
    def from_findings(cls, findings: Sequence[QcFinding]) -> QcReport:
        """Build one report from a flat finding sequence."""
        return cls(findings=tuple(findings))


def merge_reports(reports: Sequence[QcReport]) -> QcReport:
    """Merge multiple peer reports into one aggregate report."""
    merged_findings = tuple(
        finding for report in reports for finding in report.findings
    )
    return QcReport(findings=merged_findings)


@dataclass(slots=True, frozen=True)
class QuickQcContext:
    """Shared sample-quality context used by live and offline quick QC."""

    summary: SmokeTestSummary
    capture_window: WindowRange
    target_window: WindowRange
    marked_window: WindowRange | None
    marked_window_end_grace_s: float
    take_id: str | None = None


@dataclass(slots=True, frozen=True)
class OfflineQcSessionContext:
    """Shared session-level context consumed by offline QC plugins."""

    manifest_path: Path
    manifest: dict[str, object]


@runtime_checkable
class QuickQcCheck(Protocol):
    """Callable sample-quality check used by quick QC runners."""

    def __call__(self, context: QuickQcContext) -> Sequence[QcFinding]:
        """Return zero or more findings for one sample-quality context."""
        ...


@runtime_checkable
class OfflineQcCheck(Protocol):
    """Callable session-level check used by future offline QC runners."""

    def __call__(self, context: OfflineQcSessionContext) -> QcReport:
        """Return one report for one session-level offline QC context."""
        ...
