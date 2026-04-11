"""Minimal quick-QC checks for RD collection attempts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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


def evaluate_capture(
    *,
    summary: SmokeTestSummary,
    target_window: WindowRange,
    marked_window: WindowRange | None,
    marked_window_end_grace_s: float,
) -> QuickQcDecision:
    """Evaluate the minimal quick-QC checks agreed for the current phase."""
    reasons: list[str] = []
    if marked_window is None:
        reasons.append(REASON_MISSING_END_MARK)
    elif marked_window.end_s > target_window.end_s + marked_window_end_grace_s:
        reasons.append(REASON_LATE_END_MARK)

    if summary.bytes_read == 0:
        reasons.append(REASON_EMPTY_CAPTURE)
    if summary.valid_packet_count == 0:
        reasons.append(REASON_NO_VALID_PACKETS)

    return QuickQcDecision(
        accepted=not reasons,
        reasons=tuple(reasons),
    )


def describe_reason(reason: str) -> str:
    """Render a stable human-readable label for one reason code."""
    descriptions = {
        REASON_MISSING_END_MARK: "missing end mark",
        REASON_LATE_END_MARK: "end mark exceeded target_window + grace",
        REASON_EMPTY_CAPTURE: "raw capture is empty",
        REASON_NO_VALID_PACKETS: "no valid packets parsed",
    }
    return descriptions.get(reason, reason)
