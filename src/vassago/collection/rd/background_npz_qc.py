"""Offline QC plugin for background RD segment artifacts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np

from vassago.collection.rd import session as collection_session
from vassago.collection.rd.paths import resolve_repo_path
from vassago.collection.rd.paths import to_repo_relative_path
from vassago.collection.rd.qc_contract import QC_PLUGIN_BACKGROUND_NPZ
from vassago.collection.rd.qc_contract import QC_SEVERITY_ERROR
from vassago.collection.rd.qc_contract import OfflineQcSessionContext
from vassago.collection.rd.qc_contract import QcFinding
from vassago.collection.rd.qc_contract import QcReport
from vassago.firmware.mmwave import config as mmwave_config
from vassago.processing.rd import artifact as rd_artifact
from vassago.processing.rd.extract import extract_rd_capture
from vassago.processing.rd.model import BackgroundRdNpzSample
from vassago.processing.rd.model import BackgroundRdSegmentIndex
from vassago.processing.rd.model import BackgroundRdSegmentRecord

if TYPE_CHECKING:
    from pathlib import Path

type JsonObject = dict[str, object]

INDEX_FIELD_PREFIX = "background/rd_segments_manifest.json"

CODE_SEGMENT_INDEX_NOT_FOUND = "background_segment_index_not_found"
CODE_SEGMENT_INDEX_LOAD_ERROR = "background_segment_index_load_error"
CODE_SEGMENT_SELECTION_REPLAY_ERROR = "background_segment_selection_replay_error"
CODE_SEGMENT_INDEX_MISMATCH = "background_segment_index_mismatch"
CODE_SEGMENT_ARTIFACT_NOT_FOUND = "background_segment_artifact_not_found"
CODE_SEGMENT_ARTIFACT_INVALID = "background_segment_artifact_invalid"


def run_background_npz_qc(context: OfflineQcSessionContext) -> QcReport:
    """Validate background rd.npz slices against deterministic replay."""
    manifest = context.manifest
    if not _is_background_collection_type(manifest.get("collection_type")):
        return QcReport.empty()
    if not _background_capture_ready_for_slice_qc(manifest):
        return QcReport.empty()

    index_path = rd_artifact.default_background_segment_index_path(
        manifest_path=context.manifest_path
    )
    raw_index, load_error = _load_background_segment_index(index_path)
    if load_error is not None:
        return QcReport.from_findings((load_error,))
    if raw_index is None:
        return QcReport.empty()

    try:
        expected_index, expected_samples = _build_expected_background_outputs(context)
    except Exception as exc:  # noqa: BLE001
        return QcReport.from_findings(
            [
                _error(
                    CODE_SEGMENT_SELECTION_REPLAY_ERROR,
                    (
                        "failed to replay deterministic background slicing from the "
                        f"stored raw capture: {exc}"
                    ),
                    field_path="background_capture.raw_uart_path",
                )
            ]
        )

    findings = [
        *_check_index_matches_expected(
            actual_index=raw_index,
            expected_index=expected_index,
        ),
        *_check_segment_artifacts(
            actual_index=raw_index,
            expected_index=expected_index,
            expected_samples=expected_samples,
        ),
    ]
    return QcReport.from_findings(findings)


def _build_expected_background_outputs(
    context: OfflineQcSessionContext,
) -> tuple[BackgroundRdSegmentIndex, dict[str, BackgroundRdNpzSample]]:
    manifest = context.manifest
    firmware_config_id = _require_str(manifest, "firmware_config_id")
    config_path = mmwave_config.get_known_config(firmware_config_id).path.resolve()
    raw_uart_path = rd_artifact.resolve_background_raw_uart_path(manifest)
    capture = extract_rd_capture(
        input_path=raw_uart_path,
        config_path=config_path,
    )
    selection = rd_artifact.select_background_windows(
        capture=capture,
        manifest=manifest,
    )

    segment_records: list[BackgroundRdSegmentRecord] = []
    expected_samples: dict[str, BackgroundRdNpzSample] = {}
    for selected_window in selection.selected_windows:
        output_path = rd_artifact.default_background_segment_output_path(
            manifest_path=context.manifest_path,
            segment_id=selected_window.segment_id,
        )
        segment_records.append(
            BackgroundRdSegmentRecord(
                segment_id=selected_window.segment_id,
                window_index=selected_window.window_index,
                start_frame_index=selected_window.start_frame_index,
                end_frame_index=selected_window.end_frame_index,
                capture_window_s=selected_window.capture_window_s,
                rd_npz_path=to_repo_relative_path(output_path),
            )
        )
        expected_samples[selected_window.segment_id] = (
            rd_artifact.build_background_rd_npz_sample(
                capture=capture,
                manifest=manifest,
                selected_window=selected_window,
            )
        )

    expected_index = BackgroundRdSegmentIndex(
        session_id=_require_str(manifest, "session_id"),
        collection_type=_require_str(manifest, "collection_type"),
        source_raw_uart_path=to_repo_relative_path(raw_uart_path),
        window_duration_s=selection.window_duration_s,
        target_segment_count=selection.target_segment_count,
        selection_seed=selection.selection_seed,
        frame_period_s=selection.frame_period_s,
        frames_per_window=selection.frames_per_window,
        total_frame_count=capture.frame_count,
        candidate_window_count=selection.candidate_window_count,
        segments=tuple(segment_records),
    )
    return expected_index, expected_samples


def _check_index_matches_expected(
    *,
    actual_index: JsonObject,
    expected_index: BackgroundRdSegmentIndex,
) -> list[QcFinding]:
    return [
        *_check_top_level_index_fields(
            actual_index=actual_index,
            expected_index=expected_index,
        ),
        *_check_segment_index_records(
            actual_index=actual_index,
            expected_index=expected_index,
        ),
    ]


def _check_top_level_index_fields(
    *,
    actual_index: JsonObject,
    expected_index: BackgroundRdSegmentIndex,
) -> list[QcFinding]:
    expected_index_dict = expected_index.as_dict()
    return [
        _error(
            CODE_SEGMENT_INDEX_MISMATCH,
            (
                f"background segment index field {field_name!r} does not "
                "match deterministic replay."
            ),
            field_path=f"{INDEX_FIELD_PREFIX}.{field_name}",
        )
        for field_name in (
            "schema_version",
            "session_id",
            "collection_type",
            "source_raw_uart_path",
            "window_duration_s",
            "target_segment_count",
            "selection_seed",
            "frame_period_s",
            "frames_per_window",
            "total_frame_count",
            "candidate_window_count",
        )
        if actual_index.get(field_name) != expected_index_dict[field_name]
    ]


def _check_segment_index_records(
    *,
    actual_index: JsonObject,
    expected_index: BackgroundRdSegmentIndex,
) -> list[QcFinding]:
    findings: list[QcFinding] = []
    raw_segments = actual_index.get("segments")
    if not isinstance(raw_segments, list):
        return [
            *findings,
            _error(
                CODE_SEGMENT_INDEX_MISMATCH,
                "background segment index field 'segments' must be a list.",
                field_path=f"{INDEX_FIELD_PREFIX}.segments",
            ),
        ]

    expected_segments = expected_index.segments
    if len(raw_segments) != len(expected_segments):
        findings.append(
            _error(
                CODE_SEGMENT_INDEX_MISMATCH,
                (
                    "background segment index segment count does not match "
                    "deterministic replay."
                ),
                field_path=f"{INDEX_FIELD_PREFIX}.segments",
            )
        )

    for segment_offset, expected_segment in enumerate(expected_segments):
        if segment_offset >= len(raw_segments):
            break
        raw_segment = raw_segments[segment_offset]
        segment_prefix = f"{INDEX_FIELD_PREFIX}.segments[{segment_offset}]"
        if not isinstance(raw_segment, dict):
            findings.append(
                _error(
                    CODE_SEGMENT_INDEX_MISMATCH,
                    "background segment record must be a JSON object.",
                    field_path=segment_prefix,
                )
            )
            continue

        findings.extend(
            _check_segment_record_fields(
                raw_segment=raw_segment,
                expected_segment=expected_segment,
                segment_prefix=segment_prefix,
            )
        )

    return findings


def _check_segment_record_fields(
    *,
    raw_segment: JsonObject,
    expected_segment: BackgroundRdSegmentRecord,
    segment_prefix: str,
) -> list[QcFinding]:
    findings = [
        _error(
            CODE_SEGMENT_INDEX_MISMATCH,
            (
                f"background segment field {field_name!r} does not "
                "match deterministic replay."
            ),
            field_path=f"{segment_prefix}.{field_name}",
        )
        for field_name in (
            "segment_id",
            "window_index",
            "start_frame_index",
            "end_frame_index",
            "rd_npz_path",
        )
        if raw_segment.get(field_name) != getattr(expected_segment, field_name)
    ]

    raw_capture_window = raw_segment.get("capture_window")
    if not isinstance(raw_capture_window, dict):
        return [
            *findings,
            _error(
                CODE_SEGMENT_INDEX_MISMATCH,
                "background segment capture_window must be an object.",
                field_path=f"{segment_prefix}.capture_window",
            ),
        ]

    expected_capture_window = {
        "start_s": expected_segment.capture_window_s[0],
        "end_s": expected_segment.capture_window_s[1],
    }
    findings.extend(
        _error(
            CODE_SEGMENT_INDEX_MISMATCH,
            (
                f"background segment capture_window field {field_name!r} "
                "does not match deterministic replay."
            ),
            field_path=f"{segment_prefix}.capture_window.{field_name}",
        )
        for field_name in ("start_s", "end_s")
        if raw_capture_window.get(field_name) != expected_capture_window[field_name]
    )
    return findings


def _check_segment_artifacts(
    *,
    actual_index: JsonObject,
    expected_index: BackgroundRdSegmentIndex,
    expected_samples: dict[str, BackgroundRdNpzSample],
) -> list[QcFinding]:
    raw_segments = actual_index.get("segments")
    if not isinstance(raw_segments, list):
        return []

    findings: list[QcFinding] = []
    for segment_offset, expected_segment in enumerate(expected_index.segments):
        if segment_offset >= len(raw_segments):
            break
        raw_segment = raw_segments[segment_offset]
        segment_prefix = f"{INDEX_FIELD_PREFIX}.segments[{segment_offset}]"
        if not isinstance(raw_segment, dict):
            continue

        raw_rd_npz_path = raw_segment.get("rd_npz_path")
        if not isinstance(raw_rd_npz_path, str) or not raw_rd_npz_path:
            continue

        resolved_rd_npz_path = resolve_repo_path(raw_rd_npz_path)
        if not resolved_rd_npz_path.is_file():
            findings.append(
                _error(
                    CODE_SEGMENT_ARTIFACT_NOT_FOUND,
                    (
                        "background rd.npz artifact was not found: "
                        f"{resolved_rd_npz_path}"
                    ),
                    field_path=f"{segment_prefix}.rd_npz_path",
                )
            )
            continue

        findings.extend(
            _check_one_segment_npz(
                npz_path=resolved_rd_npz_path,
                expected_sample=expected_samples[expected_segment.segment_id],
                segment_prefix=segment_prefix,
            )
        )

    return findings


def _check_one_segment_npz(
    *,
    npz_path: Path,
    expected_sample: BackgroundRdNpzSample,
    segment_prefix: str,
) -> list[QcFinding]:
    expected_arrays = expected_sample.as_arrays()
    try:
        with np.load(npz_path, allow_pickle=False) as payload:
            findings: list[QcFinding] = []
            for field_name, expected_array in expected_arrays.items():
                if field_name not in payload.files:
                    findings.append(
                        _error(
                            CODE_SEGMENT_ARTIFACT_INVALID,
                            (
                                "background rd.npz is missing required field "
                                f"{field_name!r}."
                            ),
                            field_path=f"{segment_prefix}.{field_name}",
                        )
                    )
                    continue

                actual_array = payload[field_name]
                if field_name == "rd" and actual_array.dtype != np.uint16:
                    findings.append(
                        _error(
                            CODE_SEGMENT_ARTIFACT_INVALID,
                            "background rd.npz field 'rd' must use dtype uint16.",
                            field_path=f"{segment_prefix}.rd",
                        )
                    )
                    continue
                if not _arrays_equal(actual_array, expected_array):
                    findings.append(
                        _error(
                            CODE_SEGMENT_ARTIFACT_INVALID,
                            (
                                f"background rd.npz field {field_name!r} does not "
                                "match deterministic replay output."
                            ),
                            field_path=f"{segment_prefix}.{field_name}",
                        )
                    )
            return findings
    except Exception as exc:  # noqa: BLE001
        return [
            _error(
                CODE_SEGMENT_ARTIFACT_INVALID,
                f"failed to load background rd.npz artifact: {exc}",
                field_path=f"{segment_prefix}.rd_npz_path",
            )
        ]


def _background_capture_ready_for_slice_qc(manifest: JsonObject) -> bool:
    background_capture = manifest.get("background_capture")
    if not isinstance(background_capture, dict):
        return False

    raw_uart_path = background_capture.get("raw_uart_path")
    status = background_capture.get("status")
    if (
        status != collection_session.BACKGROUND_CAPTURE_STATUS_COMPLETED
        or not isinstance(raw_uart_path, str)
        or not raw_uart_path
    ):
        return False

    resolved_raw_uart_path = resolve_repo_path(raw_uart_path)
    if not resolved_raw_uart_path.is_file():
        return False

    file_size = resolved_raw_uart_path.stat().st_size
    if file_size == 0:
        return False

    recorded_bytes = background_capture.get("recorded_bytes")
    if not isinstance(recorded_bytes, int) or isinstance(recorded_bytes, bool):
        return False
    return recorded_bytes >= 0 and file_size == recorded_bytes


def _is_background_collection_type(value: object) -> bool:
    return value in {
        collection_session.COLLECTION_TYPE_NORMAL_ACTIVITY,
        collection_session.COLLECTION_TYPE_WHITE_SPACE,
    }


def _load_background_segment_index(
    index_path: Path,
) -> tuple[JsonObject | None, QcFinding | None]:
    if not index_path.is_file():
        return None, _error(
            CODE_SEGMENT_INDEX_NOT_FOUND,
            (
                "background segment index/manifest was not found. "
                "Run `vassago processing rd extract --manifest ...` first."
            ),
            field_path=INDEX_FIELD_PREFIX,
        )

    try:
        raw_index = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, _error(
            CODE_SEGMENT_INDEX_LOAD_ERROR,
            f"failed to load background segment index/manifest: {exc}",
            field_path=INDEX_FIELD_PREFIX,
        )
    if not isinstance(raw_index, dict):
        return None, _error(
            CODE_SEGMENT_INDEX_LOAD_ERROR,
            "background segment index/manifest root must be a JSON object.",
            field_path=INDEX_FIELD_PREFIX,
        )
    return raw_index, None


def _arrays_equal(actual_array: np.ndarray, expected_array: np.ndarray) -> bool:
    if actual_array.shape != expected_array.shape:
        return False
    if actual_array.dtype.kind == "f" or expected_array.dtype.kind == "f":
        return np.array_equal(actual_array, expected_array, equal_nan=True)
    return np.array_equal(actual_array, expected_array)


def _require_str(data: JsonObject, key: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value:
        return value

    msg = f"Field {key!r} must be a non-empty string."
    raise ValueError(msg)


def _error(code: str, message: str, *, field_path: str | None) -> QcFinding:
    return QcFinding(
        plugin=QC_PLUGIN_BACKGROUND_NPZ,
        severity=QC_SEVERITY_ERROR,
        code=code,
        message=message,
        field_path=field_path,
    )
