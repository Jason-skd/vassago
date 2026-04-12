"""Session and manifest primitives for RD collection workflows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from vassago.collection.rd.paths import resolve_repo_path
from vassago.collection.rd.paths import to_repo_relative_path

if TYPE_CHECKING:
    from vassago.collection.rd.config import CollectionProfile
    from vassago.collection.rd.config import WindowRange

DEFAULT_SESSIONS_ROOT = Path("data/collection/rd/sessions")
MANIFEST_FILENAME = "manifest.json"
RAW_UART_FILENAME = "raw_uart.bin"
SESSION_SCHEMA_VERSION = "collection_rd_session_v4"
SESSION_STATUS_PLANNED = "planned"
SESSION_STATUS_IN_PROGRESS = "in_progress"
SESSION_STATUS_COMPLETED = "completed"
SESSION_STATUS_INTERRUPTED = "interrupted"
TAKE_STATUS_PLANNED = "planned"
TAKE_STATUS_ACCEPTED = "accepted"

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
    gesture: str
    cli_port: str
    data_port: str
    data_baudrate: int


@dataclass(slots=True, frozen=True)
class SessionSummary:
    """Compact information shown when listing resumable sessions."""

    session_id: str
    manifest_path: Path
    session_status: str
    subject_name: str
    gesture: str
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

    return {
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_id": build_session_id(
            now=now,
            subject_name=session_input.subject_name,
            gesture=session_input.gesture,
        ),
        "created_at": created_at,
        "updated_at": created_at,
        "session_status": SESSION_STATUS_PLANNED,
        "batch_size": profile.batch_size,
        "subject_name": session_input.subject_name,
        "hand": session_input.hand,
        "distance_m": session_input.distance_m,
        "angle_deg": session_input.angle_deg,
        "environment": session_input.environment,
        "operator_name": session_input.operator_name,
        "note": session_input.note,
        "radar_id": session_input.radar_id,
        "firmware_id": session_input.firmware_id,
        "gesture": session_input.gesture,
        "gesture_options": list(profile.gestures),
        "environment_options": list(profile.environments),
        "config_id": profile.config_id,
        "cli_port": session_input.cli_port,
        "data_port": session_input.data_port,
        "data_baudrate": session_input.data_baudrate,
        "config_snapshot": profile.as_snapshot(),
        "takes": build_take_plan(batch_size=profile.batch_size),
    }


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


def load_manifest(manifest_path: Path) -> JsonObject:
    """Load one manifest JSON file."""
    resolved_path = resolve_repo_path(manifest_path)
    data = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"Manifest root must be an object: {resolved_path}"
        raise TypeError(msg)
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
                subject_name=_require_str(manifest, "subject_name"),
                gesture=_require_str(manifest, "gesture"),
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


def accept_take(
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


def build_session_id(
    *,
    now: datetime,
    subject_name: str,
    gesture: str,
) -> str:
    """Build a stable session identifier from the runtime inputs."""
    return (
        f"{now.strftime('%Y%m%d_%H%M%S')}_{_slugify(subject_name)}_{_slugify(gesture)}"
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


def _require_str(data: JsonObject, key: str) -> str:
    """Require one string field from a manifest object."""
    value = data.get(key)
    if isinstance(value, str) and value:
        return value

    msg = f"Manifest field {key!r} must be a string."
    raise ValueError(msg)
