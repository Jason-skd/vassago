"""Manifest contract checks used by offline RD collection QC."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TypeGuard

from vassago.collection.rd import session as collection_session
from vassago.collection.rd.qc_contract import MANIFEST_SNAPSHOT_COMPARISON_RULES
from vassago.collection.rd.qc_contract import MANIFEST_SNAPSHOT_MEMBERSHIP_RULES
from vassago.collection.rd.qc_contract import MANIFEST_TAKE_EXTRACT_FIELDS
from vassago.collection.rd.qc_contract import MANIFEST_TOP_LEVEL_EXTRACT_FIELDS
from vassago.collection.rd.qc_contract import QC_PLUGIN_METADATA
from vassago.collection.rd.qc_contract import QC_SEVERITY_ERROR
from vassago.collection.rd.qc_contract import OfflineQcSessionContext
from vassago.collection.rd.qc_contract import QcFinding
from vassago.collection.rd.qc_contract import QcReport
from vassago.collection.rd.qc_contract import QcSeverity

type JsonObject = dict[str, object]
type Validator = Callable[[object], bool]

MISSING = object()

CODE_MISSING_FIELD = "missing_required_field"
CODE_INVALID_FIELD = "invalid_field_value"
CODE_TAKE_COUNT_MISMATCH = "take_count_mismatch"
CODE_SNAPSHOT_MISMATCH = "top_level_snapshot_mismatch"
CODE_MEMBERSHIP_VIOLATION = "top_level_membership_violation"


@dataclass(slots=True, frozen=True)
class FieldSpec:
    """Describe one required field and how its value is validated."""

    expected: str
    validator: Validator


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_optional_string(value: object) -> bool:
    return value is None or isinstance(value, str)


def _is_optional_non_empty_str(value: object) -> bool:
    return value is None or _is_non_empty_string(value)


def _is_optional_number(value: object) -> bool:
    return value is None or _is_number(value)


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_positive_number(value: object) -> bool:
    if not _is_number(value):
        return False
    return value > 0


def _is_non_negative_number(value: object) -> bool:
    if not _is_number(value):
        return False
    return value >= 0


def _is_non_empty_string_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_is_non_empty_string(item) for item in value)
    )


def _is_gesture_duration_mapping(value: object) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and all(_is_non_empty_string(key) for key in value)
        and all(_is_positive_number(duration) for duration in value.values())
    )


def _is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _is_valid_hand(value: object) -> bool:
    return value in {"left", "right"}


def _is_optional_iso_timestamp(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_optional_window_object(value: object) -> bool:
    return value is None or _is_window_object(value)


def _is_window_object(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    start_s = value.get("start_s")
    end_s = value.get("end_s")
    if not _is_number(start_s) or not _is_number(end_s):
        return False
    return end_s >= start_s


TOP_LEVEL_FIELD_SPECS: dict[str, FieldSpec] = {
    "schema_version": FieldSpec("non-empty string", _is_non_empty_string),
    "session_id": FieldSpec("non-empty string", _is_non_empty_string),
    "subject_name": FieldSpec("non-empty string", _is_non_empty_string),
    "hand": FieldSpec("'left' or 'right'", _is_valid_hand),
    "distance_m": FieldSpec("number or null", _is_optional_number),
    "angle_deg": FieldSpec("number or null", _is_optional_number),
    "environment": FieldSpec("non-empty string", _is_non_empty_string),
    "operator_name": FieldSpec("non-empty string", _is_non_empty_string),
    "note": FieldSpec("string or null", _is_optional_string),
    "radar_id": FieldSpec("non-empty string", _is_non_empty_string),
    "firmware_id": FieldSpec("non-empty string", _is_non_empty_string),
    "gesture": FieldSpec("non-empty string", _is_non_empty_string),
    "batch_size": FieldSpec("positive integer", _is_positive_int),
    "gesture_options": FieldSpec("non-empty string list", _is_non_empty_string_list),
    "environment_options": FieldSpec(
        "non-empty string list",
        _is_non_empty_string_list,
    ),
    "cli_port": FieldSpec("non-empty string", _is_non_empty_string),
    "data_port": FieldSpec("non-empty string", _is_non_empty_string),
    "data_baudrate": FieldSpec("positive integer", _is_positive_int),
    "takes": FieldSpec("list", _is_list),
}

TAKE_FIELD_SPECS: dict[str, FieldSpec] = {
    "take_index": FieldSpec("positive integer", _is_positive_int),
    "take_id": FieldSpec("non-empty string", _is_non_empty_string),
    "status": FieldSpec("non-empty string", _is_non_empty_string),
    "raw_uart_path": FieldSpec("non-empty string or null", _is_optional_non_empty_str),
    "accepted_at": FieldSpec("ISO timestamp or null", _is_optional_iso_timestamp),
    "capture_window": FieldSpec("window object or null", _is_optional_window_object),
    "target_window": FieldSpec("window object or null", _is_optional_window_object),
    "marked_window": FieldSpec("window object or null", _is_optional_window_object),
}

SNAPSHOT_FIELD_SPECS: dict[tuple[str, ...], FieldSpec] = {
    ("schema_version",): FieldSpec("non-empty string", _is_non_empty_string),
    ("config_id",): FieldSpec("non-empty string", _is_non_empty_string),
    ("label",): FieldSpec("non-empty string", _is_non_empty_string),
    ("description",): FieldSpec("non-empty string", _is_non_empty_string),
    ("batch_size",): FieldSpec("positive integer", _is_positive_int),
    ("global", "config_id"): FieldSpec("non-empty string", _is_non_empty_string),
    ("firmware", "config_id"): FieldSpec("non-empty string", _is_non_empty_string),
    ("runtime", "capture_window_duration_s"): FieldSpec(
        "positive number",
        _is_positive_number,
    ),
    ("runtime", "countdown_duration_s"): FieldSpec(
        "positive number",
        _is_positive_number,
    ),
    ("runtime", "marked_window_end_grace_s"): FieldSpec(
        "non-negative number",
        _is_non_negative_number,
    ),
    ("runtime", "end_mark_key"): FieldSpec("non-empty string", _is_non_empty_string),
    ("defaults", "hand"): FieldSpec("'left' or 'right'", _is_valid_hand),
    ("defaults", "distance_m"): FieldSpec("number or null", _is_optional_number),
    ("defaults", "angle_deg"): FieldSpec("number or null", _is_optional_number),
    ("defaults", "environment"): FieldSpec("non-empty string", _is_non_empty_string),
    ("defaults", "radar_id"): FieldSpec("non-empty string", _is_non_empty_string),
    ("defaults", "firmware_id"): FieldSpec("non-empty string", _is_non_empty_string),
    ("serial", "cli_port"): FieldSpec("string or null", _is_optional_string),
    ("serial", "data_port"): FieldSpec("string or null", _is_optional_string),
    ("serial", "cli_baudrate"): FieldSpec("positive integer", _is_positive_int),
    ("serial", "data_baudrate"): FieldSpec("positive integer", _is_positive_int),
    ("options", "gestures"): FieldSpec(
        "non-empty string list", _is_non_empty_string_list
    ),
    ("options", "environments"): FieldSpec(
        "non-empty string list",
        _is_non_empty_string_list,
    ),
    ("gesture_target_durations",): FieldSpec(
        "gesture-to-duration mapping",
        _is_gesture_duration_mapping,
    ),
}


def run_metadata_qc(context: OfflineQcSessionContext) -> QcReport:
    """Validate the manifest public contract and snapshot provenance shape."""
    manifest = context.manifest
    findings = [
        *_check_top_level_contract(manifest),
        *_check_take_contract(manifest),
        *_check_snapshot_contract(manifest),
        *_check_snapshot_alignment(manifest),
    ]
    return QcReport.from_findings(findings)


def _check_top_level_contract(manifest: JsonObject) -> list[QcFinding]:
    findings: list[QcFinding] = []
    for field_name in MANIFEST_TOP_LEVEL_EXTRACT_FIELDS:
        spec = TOP_LEVEL_FIELD_SPECS[field_name]
        if field_name not in manifest:
            findings.append(
                _error(
                    CODE_MISSING_FIELD,
                    f"manifest is missing required top-level field {field_name!r}.",
                    field_path=field_name,
                )
            )
            continue

        value = manifest[field_name]
        if not spec.validator(value):
            findings.append(
                _error(
                    CODE_INVALID_FIELD,
                    f"manifest field {field_name!r} must be {spec.expected}.",
                    field_path=field_name,
                )
            )

    takes_value = manifest.get("takes")
    batch_size = manifest.get("batch_size")
    if (
        _is_list(takes_value)
        and _is_positive_int(batch_size)
        and len(takes_value) != batch_size
    ):
        findings.append(
            _error(
                CODE_TAKE_COUNT_MISMATCH,
                "manifest takes length must match top-level batch_size.",
                field_path="takes",
            )
        )

    return findings


def _check_take_contract(manifest: JsonObject) -> list[QcFinding]:
    raw_takes = manifest.get("takes")
    if not isinstance(raw_takes, list):
        return []

    findings: list[QcFinding] = []
    for take_offset, raw_take in enumerate(raw_takes):
        take_prefix = f"takes[{take_offset}]"
        if not isinstance(raw_take, dict):
            findings.append(
                _error(
                    CODE_INVALID_FIELD,
                    f"{take_prefix} must be an object.",
                    field_path=take_prefix,
                )
            )
            continue

        take = raw_take
        for field_name in MANIFEST_TAKE_EXTRACT_FIELDS:
            spec = TAKE_FIELD_SPECS[field_name]
            field_path = f"{take_prefix}.{field_name}"
            if field_name not in take:
                findings.append(
                    _error(
                        CODE_MISSING_FIELD,
                        f"{take_prefix} is missing required field {field_name!r}.",
                        field_path=field_path,
                    )
                )
                continue

            value = take[field_name]
            if not spec.validator(value):
                findings.append(
                    _error(
                        CODE_INVALID_FIELD,
                        f"{field_path} must be {spec.expected}.",
                        field_path=field_path,
                    )
                )

        if take.get("status") == collection_session.TAKE_STATUS_ACCEPTED:
            findings.extend(_check_accepted_take_contract(take, take_offset))

    return findings


def _check_accepted_take_contract(
    take: JsonObject,
    take_offset: int,
) -> list[QcFinding]:
    findings: list[QcFinding] = []
    take_prefix = f"takes[{take_offset}]"
    for field_name in (
        "raw_uart_path",
        "accepted_at",
        "capture_window",
        "target_window",
    ):
        field_path = f"{take_prefix}.{field_name}"
        if take.get(field_name) is None:
            findings.append(
                _error(
                    CODE_INVALID_FIELD,
                    f"{field_path} must not be null for accepted takes.",
                    field_path=field_path,
                )
            )
    return findings


def _check_snapshot_contract(manifest: JsonObject) -> list[QcFinding]:
    raw_snapshot = manifest.get("config_snapshot")
    if not isinstance(raw_snapshot, dict):
        return [
            _error(
                CODE_MISSING_FIELD,
                "manifest is missing required config_snapshot object.",
                field_path="config_snapshot",
            )
        ]

    findings: list[QcFinding] = []
    for field_path, spec in SNAPSHOT_FIELD_SPECS.items():
        value = _lookup_nested(raw_snapshot, field_path)
        rendered_path = _render_snapshot_path(field_path)
        if value is MISSING:
            findings.append(
                _error(
                    CODE_MISSING_FIELD,
                    f"{rendered_path} is required for offline QC.",
                    field_path=rendered_path,
                )
            )
            continue

        if not spec.validator(value):
            findings.append(
                _error(
                    CODE_INVALID_FIELD,
                    f"{rendered_path} must be {spec.expected}.",
                    field_path=rendered_path,
                )
            )

    return findings


def _check_snapshot_alignment(manifest: JsonObject) -> list[QcFinding]:
    raw_snapshot = manifest.get("config_snapshot")
    if not isinstance(raw_snapshot, dict):
        return []

    findings: list[QcFinding] = []
    for rule in MANIFEST_SNAPSHOT_COMPARISON_RULES:
        top_level_spec = TOP_LEVEL_FIELD_SPECS[rule.top_level_field]
        snapshot_spec = SNAPSHOT_FIELD_SPECS[rule.snapshot_path]
        top_level_value = manifest.get(rule.top_level_field, MISSING)
        snapshot_value = _lookup_nested(raw_snapshot, rule.snapshot_path)
        if top_level_value is MISSING or snapshot_value is MISSING:
            continue
        if (
            not top_level_spec.validator(top_level_value)
            or not snapshot_spec.validator(snapshot_value)
            or top_level_value == snapshot_value
        ):
            continue

        findings.append(
            _finding(
                severity=rule.mismatch_severity,
                code=CODE_SNAPSHOT_MISMATCH,
                message=(
                    f"manifest field {rule.top_level_field!r} does not match "
                    f"{_render_snapshot_path(rule.snapshot_path)}. {rule.rationale}"
                ),
                field_path=rule.top_level_field,
            )
        )

    for rule in MANIFEST_SNAPSHOT_MEMBERSHIP_RULES:
        top_level_spec = TOP_LEVEL_FIELD_SPECS[rule.top_level_field]
        snapshot_spec = SNAPSHOT_FIELD_SPECS[rule.snapshot_path]
        top_level_value = manifest.get(rule.top_level_field, MISSING)
        snapshot_value = _lookup_nested(raw_snapshot, rule.snapshot_path)
        if top_level_value is MISSING or snapshot_value is MISSING:
            continue
        if not isinstance(snapshot_value, list):
            continue
        if (
            not top_level_spec.validator(top_level_value)
            or not snapshot_spec.validator(snapshot_value)
            or top_level_value in snapshot_value
        ):
            continue

        findings.append(
            _finding(
                severity=rule.violation_severity,
                code=CODE_MEMBERSHIP_VIOLATION,
                message=(
                    f"manifest field {rule.top_level_field!r} must belong to "
                    f"{_render_snapshot_path(rule.snapshot_path)}. {rule.rationale}"
                ),
                field_path=rule.top_level_field,
            )
        )

    return findings


def _render_snapshot_path(path: Sequence[str]) -> str:
    """Render one snapshot path for finding messages."""
    return ".".join(("config_snapshot", *path))


def _lookup_nested(
    data: Mapping[str, object],
    path: Sequence[str],
) -> object:
    """Resolve a nested mapping value or return the sentinel."""
    current: object = data
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def _finding(
    *,
    severity: QcSeverity,
    code: str,
    message: str,
    field_path: str | None,
) -> QcFinding:
    return QcFinding(
        plugin=QC_PLUGIN_METADATA,
        severity=severity,
        code=code,
        message=message,
        field_path=field_path,
    )


def _error(code: str, message: str, *, field_path: str | None) -> QcFinding:
    return _finding(
        severity=QC_SEVERITY_ERROR,
        code=code,
        message=message,
        field_path=field_path,
    )
