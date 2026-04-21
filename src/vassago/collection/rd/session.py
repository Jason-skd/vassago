"""Session and manifest primitives for RD collection workflows."""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from vassago.collection.rd import config as collection_config
from vassago.collection.rd.paths import resolve_repo_path
from vassago.collection.rd.paths import to_repo_relative_path

if TYPE_CHECKING:
    from vassago.collection.rd.config import CollectionProfile
    from vassago.collection.rd.config import WindowRange

DEFAULT_SESSIONS_ROOT = Path("data/collection/rd/sessions")
MANIFEST_FILENAME = "manifest.json"
RAW_UART_FILENAME = "raw_uart.bin"
BACKGROUND_RAW_UART_FILENAME = "background_raw_uart.bin"
SESSION_SCHEMA_VERSION = "collection_rd_session_v8"
SESSION_STATUS_PLANNED = "planned"
SESSION_STATUS_IN_PROGRESS = "in_progress"
SESSION_STATUS_COMPLETED = "completed"
SESSION_STATUS_INTERRUPTED = "interrupted"
TAKE_STATUS_PLANNED = "planned"
TAKE_STATUS_ACCEPTED = "accepted"
BACKGROUND_CAPTURE_STATUS_PLANNED = "planned"
BACKGROUND_CAPTURE_STATUS_IN_PROGRESS = "in_progress"
BACKGROUND_CAPTURE_STATUS_COMPLETED = "completed"
BACKGROUND_CAPTURE_STATUS_INTERRUPTED = "interrupted"
BACKGROUND_CAPTURE_STATUSES = (
    BACKGROUND_CAPTURE_STATUS_PLANNED,
    BACKGROUND_CAPTURE_STATUS_IN_PROGRESS,
    BACKGROUND_CAPTURE_STATUS_COMPLETED,
    BACKGROUND_CAPTURE_STATUS_INTERRUPTED,
)
COLLECTION_TYPE_GESTURE = "gesture"
COLLECTION_TYPE_NORMAL_ACTIVITY = "normal_activity"
COLLECTION_TYPE_WHITE_SPACE = "white_space"
COLLECTION_TYPES = (
    COLLECTION_TYPE_GESTURE,
    COLLECTION_TYPE_NORMAL_ACTIVITY,
    COLLECTION_TYPE_WHITE_SPACE,
)
BACKGROUND_SELECTION_POLICY_RANDOM_AFTER_CAPTURE = "random_after_capture"
BACKGROUND_SAVE_POLICY_KEEP_FULL_CAPTURE = "keep_full_capture"
BACKGROUND_SELECTION_SEED_MAX = 2**32 - 1
SYSTEM_RANDOM = random.SystemRandom()

type JsonObject = dict[str, object]


@dataclass(slots=True, frozen=True)
class SessionInitInput:
    """Resolved session inputs ready to be persisted into a manifest."""

    profile: CollectionProfile
    subject_name: str
    hand: str
    distance_m: float | None
    angle_deg: float | None
    environment: str
    operator_name: str
    note: str | None
    radar_id: str
    firmware_id: str
    firmware_config_id: str
    cli_port: str
    data_port: str
    data_baudrate: int
    collection_type: str = COLLECTION_TYPE_GESTURE
    gesture: str | None = None


@dataclass(slots=True, frozen=True)
class SessionSummary:
    """Compact information shown when listing resumable sessions."""

    session_id: str
    manifest_path: Path
    session_status: str
    collection_type: str
    subject_name: str
    gesture: str | None
    accepted_take_count: int
    remaining_take_count: int
    updated_at: str


def local_now() -> datetime:
    """Return the local time with timezone information."""
    return datetime.now(UTC).astimezone()


def initialize_session(
    *,
    session_input: SessionInitInput,
    sessions_root: Path = DEFAULT_SESSIONS_ROOT,
    now: datetime | None = None,
) -> tuple[Path, JsonObject]:
    """Create one session directory plus its initial manifest."""
    timestamp = now or local_now()
    manifest = build_session_manifest(session_input=session_input, now=timestamp)
    session_dir = resolve_repo_path(sessions_root) / _require_str(
        manifest, "session_id"
    )
    session_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = session_dir / MANIFEST_FILENAME
    write_manifest(manifest_path=manifest_path, manifest=manifest)
    return manifest_path, manifest


def build_session_manifest(
    *,
    session_input: SessionInitInput,
    now: datetime,
) -> JsonObject:
    """Build the initial manifest dictionary for one new session."""
    profile = session_input.profile
    created_at = now.isoformat()
    collection_type = _require_collection_type(session_input.collection_type)
    gesture = _resolve_session_gesture(
        collection_type=collection_type,
        gesture=session_input.gesture,
    )
    companion_profile_id = profile.default_companion_profile_id
    background_plan = None
    background_capture = None
    takes: list[JsonObject] = build_take_plan(batch_size=profile.batch_size)
    if collection_type != COLLECTION_TYPE_GESTURE:
        companion_profile = collection_config.get_collection_companion_profile(
            companion_profile_id
        )
        background_plan = build_background_plan(
            profile=profile,
            companion_profile=companion_profile,
            collection_type=collection_type,
        )
        background_capture = build_background_capture_record()
        takes = []

    manifest: JsonObject = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_id": build_session_id(
            now=now,
            subject_name=session_input.subject_name,
            session_label=gesture or collection_type,
        ),
        "created_at": created_at,
        "updated_at": created_at,
        "session_status": SESSION_STATUS_PLANNED,
        "collection_type": collection_type,
        "subject_name": session_input.subject_name,
        "hand": session_input.hand,
        "distance_m": session_input.distance_m,
        "angle_deg": session_input.angle_deg,
        "environment": session_input.environment,
        "operator_name": session_input.operator_name,
        "note": session_input.note,
        "radar_id": session_input.radar_id,
        "firmware_id": session_input.firmware_id,
        "firmware_config_id": session_input.firmware_config_id,
        "companion_profile_id": companion_profile_id,
        "background_plan": background_plan,
        "background_capture": background_capture,
        "gesture_options": list(profile.gestures),
        "environment_options": list(profile.environments),
        "cli_port": session_input.cli_port,
        "data_port": session_input.data_port,
        "data_baudrate": session_input.data_baudrate,
        "config_snapshot": profile.as_snapshot(),
        "takes": takes,
    }
    if gesture is not None:
        manifest["gesture"] = gesture
    return manifest


def build_take_plan(
    *,
    batch_size: int,
) -> list[JsonObject]:
    """Build the planned take list for one session manifest."""
    return [
        {
            "take_index": take_index,
            "take_id": f"take{take_index:02d}",
            "status": TAKE_STATUS_PLANNED,
            "raw_uart_path": None,
            "accepted_at": None,
            "capture_window": None,
            "target_window": None,
            "marked_window": None,
        }
        for take_index in range(1, batch_size + 1)
    ]


def build_background_plan(
    *,
    profile: CollectionProfile,
    companion_profile: collection_config.CollectionCompanionProfile,
    collection_type: str,
) -> JsonObject:
    """Build the persisted background capture plan derived at session init."""
    if collection_type == COLLECTION_TYPE_GESTURE:
        msg = "Background plan is only valid for background collection types."
        raise ValueError(msg)

    global_config = collection_config.load_collection_global_config_by_id(
        profile.global_config_id
    )
    sample_ratio = companion_profile.sample_ratio_for(collection_type=collection_type)
    window_duration_s = global_config.capture_window_duration_s
    target_segment_count = math.ceil(profile.batch_size * sample_ratio)
    planned_recording_duration_s = (
        target_segment_count
        * window_duration_s
        * companion_profile.default_recording_duration_multiplier
    )
    return {
        "sample_ratio": sample_ratio,
        "default_recording_duration_multiplier": (
            companion_profile.default_recording_duration_multiplier
        ),
        "window_duration_s": window_duration_s,
        "target_segment_count": target_segment_count,
        "planned_recording_duration_s": planned_recording_duration_s,
        "selection_policy": BACKGROUND_SELECTION_POLICY_RANDOM_AFTER_CAPTURE,
        "save_policy": BACKGROUND_SAVE_POLICY_KEEP_FULL_CAPTURE,
        "selection_seed": SYSTEM_RANDOM.randint(0, BACKGROUND_SELECTION_SEED_MAX),
    }


def build_background_capture_record() -> JsonObject:
    """Build the persisted runtime state used by background sessions."""
    return {
        "status": BACKGROUND_CAPTURE_STATUS_PLANNED,
        "raw_uart_path": None,
        "started_at": None,
        "completed_at": None,
        "interrupted_at": None,
        "recording_duration_s": None,
        "recorded_bytes": None,
    }


def load_manifest(manifest_path: Path) -> JsonObject:
    """Load one manifest JSON file."""
    resolved_path = resolve_repo_path(manifest_path)
    data = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"Manifest root must be an object: {resolved_path}"
        raise TypeError(msg)
    _backfill_legacy_manifest_fields(data)
    return data


def write_manifest(
    *,
    manifest_path: Path,
    manifest: JsonObject,
) -> None:
    """Persist one manifest JSON file with stable formatting."""
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def list_unfinished_sessions(
    *,
    sessions_root: Path = DEFAULT_SESSIONS_ROOT,
) -> list[SessionSummary]:
    """List non-completed sessions available for resume."""
    sessions_path = resolve_repo_path(sessions_root)
    if not sessions_path.exists():
        return []

    summaries: list[SessionSummary] = []
    for manifest_path in sorted(sessions_path.glob(f"*/{MANIFEST_FILENAME}")):
        manifest = load_manifest(manifest_path)
        session_status = _require_str(manifest, "session_status")
        if session_status == SESSION_STATUS_COMPLETED:
            continue

        summaries.append(
            SessionSummary(
                session_id=_require_str(manifest, "session_id"),
                manifest_path=manifest_path,
                session_status=session_status,
                collection_type=_require_str(manifest, "collection_type"),
                subject_name=_require_str(manifest, "subject_name"),
                gesture=_optional_str(manifest, "gesture"),
                accepted_take_count=count_accepted_takes(manifest),
                remaining_take_count=count_remaining_takes(manifest),
                updated_at=_require_str(manifest, "updated_at"),
            ),
        )

    return summaries


def count_accepted_takes(manifest: JsonObject) -> int:
    """Count accepted takes from one manifest."""
    return sum(
        1
        for take in _require_takes(manifest)
        if _require_str(take, "status") == TAKE_STATUS_ACCEPTED
    )


def count_remaining_takes(manifest: JsonObject) -> int:
    """Count still-pending takes from one manifest."""
    return sum(
        1
        for take in _require_takes(manifest)
        if _require_str(take, "status") != TAKE_STATUS_ACCEPTED
    )


def count_total_takes(manifest: JsonObject) -> int:
    """Count planned takes from one manifest."""
    return len(_require_takes(manifest))


def next_pending_take(manifest: JsonObject) -> JsonObject | None:
    """Return the next non-accepted take, if any."""
    for take in _require_takes(manifest):
        if _require_str(take, "status") != TAKE_STATUS_ACCEPTED:
            return take
    return None


def update_session_status(
    manifest: JsonObject,
    *,
    status: str,
    now: datetime | None = None,
) -> None:
    """Update the manifest-level session status and timestamp."""
    manifest["session_status"] = status
    manifest["updated_at"] = (now or local_now()).isoformat()


def accept_take(  # noqa: PLR0913
    *,
    manifest: JsonObject,
    take: JsonObject,
    raw_uart_path: Path,
    capture_window: WindowRange,
    target_window: WindowRange,
    marked_window: WindowRange | None,
    accepted_at: datetime | None = None,
) -> None:
    """Mark one take as accepted and attach its persisted artifact path."""
    timestamp = accepted_at or local_now()
    take["status"] = TAKE_STATUS_ACCEPTED
    take["raw_uart_path"] = to_repo_relative_path(raw_uart_path)
    take["accepted_at"] = timestamp.isoformat()
    take["capture_window"] = capture_window.as_dict()
    take["target_window"] = target_window.as_dict()
    take["marked_window"] = (
        marked_window.as_dict() if marked_window is not None else None
    )
    manifest["updated_at"] = timestamp.isoformat()


def build_take_output_path(*, manifest_path: Path, take: JsonObject) -> Path:
    """Return the destination path for one accepted raw UART capture."""
    take_id = _require_str(take, "take_id")
    take_dir = manifest_path.parent / "takes" / take_id
    take_dir.mkdir(parents=True, exist_ok=True)
    return take_dir / RAW_UART_FILENAME


def build_background_output_path(*, manifest_path: Path) -> Path:
    """Return the destination path for one background continuous raw capture."""
    background_dir = manifest_path.parent / "background"
    background_dir.mkdir(parents=True, exist_ok=True)
    return background_dir / BACKGROUND_RAW_UART_FILENAME


def mark_background_capture_started(
    *,
    manifest: JsonObject,
    raw_uart_path: Path,
    started_at: datetime | None = None,
) -> None:
    """Persist the start of one background continuous capture."""
    timestamp = started_at or local_now()
    background_capture = _require_background_capture(manifest)
    background_capture["status"] = BACKGROUND_CAPTURE_STATUS_IN_PROGRESS
    background_capture["raw_uart_path"] = to_repo_relative_path(raw_uart_path)
    background_capture["started_at"] = timestamp.isoformat()
    background_capture["completed_at"] = None
    background_capture["interrupted_at"] = None
    background_capture["recording_duration_s"] = None
    background_capture["recorded_bytes"] = None
    manifest["updated_at"] = timestamp.isoformat()


def complete_background_capture(
    *,
    manifest: JsonObject,
    recording_duration_s: float,
    recorded_bytes: int,
    completed_at: datetime | None = None,
) -> None:
    """Persist successful completion details for a background capture."""
    timestamp = completed_at or local_now()
    background_capture = _require_background_capture(manifest)
    background_capture["status"] = BACKGROUND_CAPTURE_STATUS_COMPLETED
    background_capture["completed_at"] = timestamp.isoformat()
    background_capture["interrupted_at"] = None
    background_capture["recording_duration_s"] = recording_duration_s
    background_capture["recorded_bytes"] = recorded_bytes
    manifest["updated_at"] = timestamp.isoformat()


def interrupt_background_capture(
    *,
    manifest: JsonObject,
    recording_duration_s: float,
    recorded_bytes: int,
    interrupted_at: datetime | None = None,
) -> None:
    """Persist interruption details for a background capture."""
    timestamp = interrupted_at or local_now()
    background_capture = _require_background_capture(manifest)
    background_capture["status"] = BACKGROUND_CAPTURE_STATUS_INTERRUPTED
    background_capture["completed_at"] = None
    background_capture["interrupted_at"] = timestamp.isoformat()
    background_capture["recording_duration_s"] = recording_duration_s
    background_capture["recorded_bytes"] = recorded_bytes
    manifest["updated_at"] = timestamp.isoformat()


def build_session_id(
    *,
    now: datetime,
    subject_name: str,
    session_label: str,
) -> str:
    """Build a stable session identifier from the runtime inputs."""
    return (
        f"{now.strftime('%Y%m%d_%H%M%S')}_{_slugify(subject_name)}_"
        f"{_slugify(session_label)}"
    )


def _slugify(value: str) -> str:
    """Normalize one value for filesystem-safe session identifiers."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return normalized.strip("_") or "unknown"


def _require_takes(manifest: JsonObject) -> list[JsonObject]:
    """Return the manifest take list with lightweight validation."""
    raw_takes = manifest.get("takes")
    if not isinstance(raw_takes, list):
        msg = "Manifest is missing a takes list."
        raise TypeError(msg)

    takes: list[JsonObject] = []
    for raw_take in raw_takes:
        if not isinstance(raw_take, dict):
            msg = "Every take entry must be an object."
            raise TypeError(msg)
        takes.append(raw_take)
    return takes


def _require_background_capture(manifest: JsonObject) -> JsonObject:
    """Return the manifest background_capture object with lightweight validation."""
    raw_background_capture = manifest.get("background_capture")
    if not isinstance(raw_background_capture, dict):
        msg = "Manifest is missing a background_capture object."
        raise TypeError(msg)
    return raw_background_capture


def _require_str(data: JsonObject, key: str) -> str:
    """Require one string field from a manifest object."""
    value = data.get(key)
    if isinstance(value, str) and value:
        return value

    msg = f"Manifest field {key!r} must be a string."
    raise ValueError(msg)


def _optional_str(data: JsonObject, key: str) -> str | None:
    """Return one optional non-empty string field if present."""
    value = data.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _resolve_session_gesture(
    *,
    collection_type: str,
    gesture: str | None,
) -> str | None:
    """Normalize the optional session gesture for one collection branch."""
    if collection_type != COLLECTION_TYPE_GESTURE:
        return None
    if isinstance(gesture, str) and gesture:
        return gesture

    msg = "Gesture sessions require a non-empty gesture."
    raise ValueError(msg)


def _require_collection_type(value: str) -> str:
    """Validate that one session collection_type is supported."""
    if value in COLLECTION_TYPES:
        return value

    msg = f"Unsupported collection_type: {value!r}"
    raise ValueError(msg)


def _backfill_legacy_manifest_fields(manifest: JsonObject) -> None:
    """Backfill newly required contract fields for legacy persisted manifests."""
    if "collection_type" not in manifest:
        manifest["collection_type"] = COLLECTION_TYPE_GESTURE
    if "background_plan" not in manifest:
        manifest["background_plan"] = None
    if "background_capture" not in manifest:
        manifest["background_capture"] = None

    raw_snapshot = manifest.get("config_snapshot")
    if not isinstance(raw_snapshot, dict):
        return

    default_companion_profile_id = _infer_default_companion_profile_id(raw_snapshot)
    if default_companion_profile_id is None:
        return

    if "default_companion_profile_id" not in raw_snapshot:
        raw_snapshot["default_companion_profile_id"] = default_companion_profile_id
    if "companion_profile_id" not in manifest:
        manifest["companion_profile_id"] = default_companion_profile_id


def _infer_default_companion_profile_id(raw_snapshot: JsonObject) -> str | None:
    """Infer the companion profile id for legacy manifests that predate the field."""
    raw_default_companion_profile_id = raw_snapshot.get("default_companion_profile_id")
    if (
        isinstance(raw_default_companion_profile_id, str)
        and raw_default_companion_profile_id
    ):
        return raw_default_companion_profile_id

    raw_profile_config_id = raw_snapshot.get("config_id")
    if not isinstance(raw_profile_config_id, str) or not raw_profile_config_id:
        return None

    try:
        profile = collection_config.get_collection_profile(raw_profile_config_id)
    except Exception:  # noqa: BLE001
        return None
    return profile.default_companion_profile_id
