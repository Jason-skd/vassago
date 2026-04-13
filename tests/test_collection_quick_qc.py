from __future__ import annotations

from vassago.collection.rd import config as collection_config
from vassago.collection.rd import qc_contract
from vassago.collection.rd import quick_qc
from vassago.firmware.mmwave.protocol import SmokeTestSummary


def test_manifest_top_level_qc_contract_exposes_option_mirrors() -> None:
    assert "firmware_config_id" in qc_contract.MANIFEST_TOP_LEVEL_EXTRACT_FIELDS
    assert "gesture_options" in qc_contract.MANIFEST_TOP_LEVEL_EXTRACT_FIELDS
    assert "environment_options" in qc_contract.MANIFEST_TOP_LEVEL_EXTRACT_FIELDS
    assert "batch_size" not in qc_contract.MANIFEST_TOP_LEVEL_EXTRACT_FIELDS

    comparison_rules = {
        rule.top_level_field: rule
        for rule in qc_contract.MANIFEST_SNAPSHOT_COMPARISON_RULES
    }

    assert (
        comparison_rules["firmware_config_id"].mismatch_severity
        == qc_contract.QC_SEVERITY_WARN
    )
    assert (
        comparison_rules["gesture_options"].mismatch_severity
        == qc_contract.QC_SEVERITY_ERROR
    )


def test_run_quick_qc_returns_empty_report_for_valid_capture() -> None:
    context = qc_contract.QuickQcContext(
        summary=_build_summary(bytes_read=128, valid_packet_count=4),
        capture_window=collection_config.WindowRange(0.0, 5.0),
        target_window=collection_config.WindowRange(1.0, 2.5),
        marked_window=collection_config.WindowRange(1.0, 2.4),
        marked_window_end_grace_s=0.25,
    )

    report = quick_qc.run_quick_qc(context=context)
    decision = quick_qc.evaluate_capture(
        summary=context.summary,
        capture_window=context.capture_window,
        target_window=context.target_window,
        marked_window=context.marked_window,
        marked_window_end_grace_s=context.marked_window_end_grace_s,
    )

    assert report.findings == ()
    assert report.has_errors is False
    assert decision.accepted is True
    assert decision.reasons == ()


def test_run_quick_qc_maps_blocking_findings_back_to_decision_reasons() -> None:
    context = qc_contract.QuickQcContext(
        summary=_build_summary(bytes_read=0, valid_packet_count=0),
        capture_window=collection_config.WindowRange(0.0, 5.0),
        target_window=collection_config.WindowRange(1.0, 2.5),
        marked_window=None,
        marked_window_end_grace_s=0.25,
    )

    report = quick_qc.run_quick_qc(context=context)
    decision = quick_qc.evaluate_capture(
        summary=context.summary,
        capture_window=context.capture_window,
        target_window=context.target_window,
        marked_window=context.marked_window,
        marked_window_end_grace_s=context.marked_window_end_grace_s,
    )

    assert tuple(finding.plugin for finding in report.findings) == (
        qc_contract.QC_PLUGIN_QUICK,
        qc_contract.QC_PLUGIN_QUICK,
        qc_contract.QC_PLUGIN_QUICK,
    )
    assert tuple(finding.severity for finding in report.findings) == (
        qc_contract.QC_SEVERITY_ERROR,
        qc_contract.QC_SEVERITY_ERROR,
        qc_contract.QC_SEVERITY_ERROR,
    )
    assert tuple(finding.code for finding in report.findings) == (
        quick_qc.REASON_MISSING_END_MARK,
        quick_qc.REASON_EMPTY_CAPTURE,
        quick_qc.REASON_NO_VALID_PACKETS,
    )
    assert decision.accepted is False
    assert decision.reasons == (
        quick_qc.REASON_MISSING_END_MARK,
        quick_qc.REASON_EMPTY_CAPTURE,
        quick_qc.REASON_NO_VALID_PACKETS,
    )


def _build_summary(
    *,
    bytes_read: int,
    valid_packet_count: int,
) -> SmokeTestSummary:
    return SmokeTestSummary(
        bytes_read=bytes_read,
        valid_packet_count=valid_packet_count,
        invalid_packet_count=0,
        first_frame_number=1 if valid_packet_count else None,
        last_frame_number=valid_packet_count or None,
        frame_gap_count=0,
        non_monotonic_frame_count=0,
        tlv_type_counts={},
    )
