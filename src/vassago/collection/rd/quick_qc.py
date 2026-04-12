"""Minimal quick-QC checks for RD collection attempts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vassago.collection.rd.qc_contract import QC_PLUGIN_QUICK
from vassago.collection.rd.qc_contract import QC_SEVERITY_ERROR
from vassago.collection.rd.qc_contract import QcFinding
from vassago.collection.rd.qc_contract import QcReport
from vassago.collection.rd.qc_contract import QuickQcCheck
from vassago.collection.rd.qc_contract import QuickQcContext

if TYPE_CHECKING:
    from collections.abc import Sequence

    from vassago.collection.rd.config import WindowRange
    from vassago.firmware.mmwave.protocol import SmokeTestSummary

REASON_MISSING_END_MARK = "missing_end_mark"
REASON_LATE_END_MARK = "late_end_mark"
REASON_EMPTY_CAPTURE = "empty_capture"
REASON_NO_VALID_PACKETS = "no_valid_packets"


@dataclass(slots=True, frozen=True)
class QuickQcDecision:
    """Pass/fail result for one collection attempt."""

    accepted: bool
    reasons: tuple[str, ...]


def run_quick_qc(
    *,
    context: QuickQcContext,
    checks: Sequence[QuickQcCheck] | None = None,
) -> QcReport:
    """Run the shared quick-QC checks and return a peer-style report."""
    selected_checks = checks or DEFAULT_QUICK_QC_CHECKS
    findings = tuple(finding for check in selected_checks for finding in check(context))
    return QcReport(findings=findings)


def evaluate_capture(
    *,
    summary: SmokeTestSummary,
    capture_window: WindowRange,
    target_window: WindowRange,
    marked_window: WindowRange | None,
    marked_window_end_grace_s: float,
) -> QuickQcDecision:
    """Evaluate the minimal quick-QC checks agreed for the current phase."""
    report = run_quick_qc(
        context=QuickQcContext(
            summary=summary,
            capture_window=capture_window,
            target_window=target_window,
            marked_window=marked_window,
            marked_window_end_grace_s=marked_window_end_grace_s,
        ),
    )
    reasons = tuple(
        finding.code
        for finding in report.findings
        if finding.severity == QC_SEVERITY_ERROR
    )
    return QuickQcDecision(accepted=not reasons, reasons=reasons)


def describe_reason(reason: str) -> str:
    """Render a stable human-readable label for one reason code."""
    descriptions = {
        REASON_MISSING_END_MARK: "missing end mark",
        REASON_LATE_END_MARK: "end mark exceeded target_window + grace",
        REASON_EMPTY_CAPTURE: "raw capture is empty",
        REASON_NO_VALID_PACKETS: "no valid packets parsed",
    }
    return descriptions.get(reason, reason)


def _check_marked_window(context: QuickQcContext) -> tuple[QcFinding, ...]:
    """Check whether the operator finished the marked window on time."""
    if context.marked_window is None:
        return (_error_finding(REASON_MISSING_END_MARK),)
    if (
        context.marked_window.end_s
        > context.target_window.end_s + context.marked_window_end_grace_s
    ):
        return (_error_finding(REASON_LATE_END_MARK),)
    return ()


def _check_capture_bytes(context: QuickQcContext) -> tuple[QcFinding, ...]:
    """Check whether the raw capture actually contains bytes."""
    if context.summary.bytes_read == 0:
        return (_error_finding(REASON_EMPTY_CAPTURE),)
    return ()


def _check_valid_packets(context: QuickQcContext) -> tuple[QcFinding, ...]:
    """Check whether at least one valid packet was parsed."""
    if context.summary.valid_packet_count == 0:
        return (_error_finding(REASON_NO_VALID_PACKETS),)
    return ()


def _error_finding(code: str) -> QcFinding:
    """Build one blocking quick-QC finding from a reason code."""
    return QcFinding(
        plugin=QC_PLUGIN_QUICK,
        severity=QC_SEVERITY_ERROR,
        code=code,
        message=describe_reason(code),
    )


DEFAULT_QUICK_QC_CHECKS: tuple[QuickQcCheck, ...] = (
    _check_marked_window,
    _check_capture_bytes,
    _check_valid_packets,
)
