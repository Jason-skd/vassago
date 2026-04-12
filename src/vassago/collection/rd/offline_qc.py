"""Offline QC orchestration for RD collection manifests."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from typing import TypeGuard

from vassago.collection.rd import capture as collection_capture
from vassago.collection.rd import metadata_qc
from vassago.collection.rd import quick_qc
from vassago.collection.rd import session as collection_session
from vassago.collection.rd.config import WindowRange
from vassago.collection.rd.paths import resolve_repo_path
from vassago.collection.rd.qc_contract import QC_PLUGIN_QUICK
from vassago.collection.rd.qc_contract import QC_SEVERITY_ERROR
from vassago.collection.rd.qc_contract import OfflineQcCheck
from vassago.collection.rd.qc_contract import OfflineQcSessionContext
from vassago.collection.rd.qc_contract import QcFinding
from vassago.collection.rd.qc_contract import QcReport
from vassago.collection.rd.qc_contract import QuickQcContext
from vassago.collection.rd.qc_contract import merge_reports

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

type JsonObject = dict[str, object]

CODE_MISSING_REPLAY_INPUT = "missing_replay_input"
CODE_RAW_UART_NOT_FOUND = "raw_uart_artifact_not_found"


def run_offline_qc(
    *,
    manifest_path: str | Path,
    checks: Sequence[OfflineQcCheck] | None = None,
) -> QcReport:
    """Load one manifest and execute the configured offline QC checks."""
    resolved_manifest_path = resolve_repo_path(manifest_path)
    manifest = collection_session.load_manifest(resolved_manifest_path)
    return run_offline_qc_context(
        context=OfflineQcSessionContext(
            manifest_path=resolved_manifest_path,
            manifest=manifest,
        ),
        checks=checks,
    )


def run_offline_qc_context(
    *,
    context: OfflineQcSessionContext,
    checks: Sequence[OfflineQcCheck] | None = None,
) -> QcReport:
    """Run the selected offline QC peer checks for one session context."""
    selected_checks = checks or DEFAULT_OFFLINE_QC_CHECKS
    reports = tuple(check(context) for check in selected_checks)
    return merge_reports(reports)


def run_offline_quick_qc(context: OfflineQcSessionContext) -> QcReport:
    """Replay live quick-QC on accepted takes from one persisted manifest."""
    raw_takes = context.manifest.get("takes")
    if not isinstance(raw_takes, list):
        return QcReport.empty()

    grace_s = _load_marked_window_end_grace_s(context.manifest)
    findings: list[QcFinding] = []
    for raw_take in raw_takes:
        if not isinstance(raw_take, dict):
            continue
        if raw_take.get("status") != collection_session.TAKE_STATUS_ACCEPTED:
            continue
        findings.extend(
            _replay_quick_qc_for_take(
                take=raw_take,
                marked_window_end_grace_s=grace_s,
            )
        )

    return QcReport.from_findings(findings)


def _replay_quick_qc_for_take(
    *,
    take: JsonObject,
    marked_window_end_grace_s: float | None,
) -> list[QcFinding]:
    findings: list[QcFinding] = []
    take_id = _take_id_or_none(take)

    if marked_window_end_grace_s is None:
        findings.append(
            _quick_error(
                CODE_MISSING_REPLAY_INPUT,
                (
                    "config_snapshot.runtime.marked_window_end_grace_s is "
                    "required to replay quick QC."
                ),
                take_id=take_id,
                field_path="config_snapshot.runtime.marked_window_end_grace_s",
            )
        )
        return findings

    raw_uart_path = take.get("raw_uart_path")
    if not isinstance(raw_uart_path, str) or not raw_uart_path:
        findings.append(
            _quick_error(
                CODE_MISSING_REPLAY_INPUT,
                "accepted take is missing raw_uart_path required for quick-QC replay.",
                take_id=take_id,
                field_path="raw_uart_path",
            )
        )
        return findings

    capture_window = _load_window(take, "capture_window")
    target_window = _load_window(take, "target_window")
    marked_window = _load_optional_window(take, "marked_window")
    if capture_window is None:
        findings.append(
            _quick_error(
                CODE_MISSING_REPLAY_INPUT,
                "accepted take is missing a valid capture_window.",
                take_id=take_id,
                field_path="capture_window",
            )
        )
    if target_window is None:
        findings.append(
            _quick_error(
                CODE_MISSING_REPLAY_INPUT,
                "accepted take is missing a valid target_window.",
                take_id=take_id,
                field_path="target_window",
            )
        )
    if findings:
        return findings
    if capture_window is None or target_window is None:
        return findings

    resolved_raw_uart_path = resolve_repo_path(raw_uart_path)
    if not resolved_raw_uart_path.is_file():
        return [
            _quick_error(
                CODE_RAW_UART_NOT_FOUND,
                (
                    "accepted take raw_uart artifact was not found: "
                    f"{resolved_raw_uart_path}"
                ),
                take_id=take_id,
                field_path="raw_uart_path",
            )
        ]

    summary = collection_capture.summarize_raw_capture(
        resolved_raw_uart_path.read_bytes()
    )
    report = quick_qc.run_quick_qc(
        context=QuickQcContext(
            summary=summary,
            capture_window=capture_window,
            target_window=target_window,
            marked_window=marked_window,
            marked_window_end_grace_s=marked_window_end_grace_s,
            take_id=take_id,
        )
    )
    return [_with_take_id(finding, take_id=take_id) for finding in report.findings]


def _load_marked_window_end_grace_s(manifest: JsonObject) -> float | None:
    raw_snapshot = manifest.get("config_snapshot")
    if not isinstance(raw_snapshot, dict):
        return None
    raw_runtime = raw_snapshot.get("runtime")
    if not isinstance(raw_runtime, dict):
        return None
    raw_value = raw_runtime.get("marked_window_end_grace_s")
    if _is_number(raw_value):
        return float(raw_value)
    return None


def _load_window(take: JsonObject, field_name: str) -> WindowRange | None:
    raw_value = take.get(field_name)
    if not isinstance(raw_value, dict):
        return None
    start_s = raw_value.get("start_s")
    end_s = raw_value.get("end_s")
    if not _is_number(start_s) or not _is_number(end_s):
        return None
    if end_s < start_s:
        return None
    return WindowRange(start_s=float(start_s), end_s=float(end_s))


def _load_optional_window(take: JsonObject, field_name: str) -> WindowRange | None:
    raw_value = take.get(field_name)
    if raw_value is None:
        return None
    return _load_window(take, field_name)


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _take_id_or_none(take: JsonObject) -> str | None:
    raw_take_id = take.get("take_id")
    return raw_take_id if isinstance(raw_take_id, str) and raw_take_id else None


def _with_take_id(finding: QcFinding, *, take_id: str | None) -> QcFinding:
    if take_id is None:
        return finding
    return replace(finding, take_id=take_id)


def _quick_error(
    code: str,
    message: str,
    *,
    take_id: str | None,
    field_path: str | None,
) -> QcFinding:
    return QcFinding(
        plugin=QC_PLUGIN_QUICK,
        severity=QC_SEVERITY_ERROR,
        code=code,
        message=message,
        field_path=field_path,
        take_id=take_id,
    )


DEFAULT_OFFLINE_QC_CHECKS: tuple[OfflineQcCheck, ...] = (
    metadata_qc.run_metadata_qc,
    run_offline_quick_qc,
)
