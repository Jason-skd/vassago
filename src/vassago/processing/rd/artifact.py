"""Canonical rd.npz artifact writing helpers."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any
from typing import TypeGuard

import numpy as np

from vassago.collection.rd import session as collection_session
from vassago.collection.rd.config import WindowRange
from vassago.collection.rd.paths import resolve_repo_path
from vassago.collection.rd.paths import to_repo_relative_path
from vassago.firmware.mmwave import config as mmwave_config
from vassago.processing.rd.extract import extract_rd_capture
from vassago.processing.rd.model import BackgroundRdNpzSample
from vassago.processing.rd.model import BackgroundRdSegmentIndex
from vassago.processing.rd.model import BackgroundRdSegmentRecord
from vassago.processing.rd.model import ExtractedRdCapture
from vassago.processing.rd.model import RdNpzSample

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_RD_ARTIFACT_FILENAME = "rd.npz"
DEFAULT_BACKGROUND_SEGMENTS_DIRNAME = "segments"
DEFAULT_BACKGROUND_SEGMENT_INDEX_FILENAME = "rd_segments_manifest.json"

type JsonObject = dict[str, object]
type NpzSample = RdNpzSample | BackgroundRdNpzSample


class RdArtifactExistsError(FileExistsError):
    """Raised when rd.npz already exists and overwrite is disabled."""


@dataclass(slots=True, frozen=True)
class _SelectedBackgroundWindow:
    """One selected fixed-duration window inside a background capture."""

    segment_id: str
    window_index: int
    start_frame_index: int
    end_frame_index: int
    capture_window_s: tuple[float, float]


@dataclass(slots=True, frozen=True)
class _BackgroundWindowSelection:
    """Resolved background window-selection plan for one manifest."""

    window_duration_s: float
    target_segment_count: int
    selection_seed: int
    frame_period_s: float
    frames_per_window: int
    candidate_window_count: int
    selected_windows: tuple[_SelectedBackgroundWindow, ...]


@dataclass(slots=True, frozen=True)
class RdExtractManifestResult:
    """One rd.npz extraction result bound to one collection manifest."""

    manifest_path: Path
    written_paths: tuple[Path, ...]
    error: str | None = None


@dataclass(slots=True, frozen=True)
class RdExtractAllRunResult:
    """Aggregated full-repository rd.npz extraction results."""

    manifest_results: tuple[RdExtractManifestResult, ...]

    @property
    def checked_manifest_count(self) -> int:
        """Return how many manifests were checked in this run."""
        return len(self.manifest_results)

    @property
    def written_artifact_count(self) -> int:
        """Return how many rd.npz artifacts were written in this run."""
        return sum(len(result.written_paths) for result in self.manifest_results)

    @property
    def failed_manifest_count(self) -> int:
        """Return how many manifests failed extraction."""
        return sum(1 for result in self.manifest_results if result.error is not None)


def extract_all_sessions(
    *,
    sessions_root: str | Path = collection_session.DEFAULT_SESSIONS_ROOT,
    overwrite: bool = False,
) -> RdExtractAllRunResult:
    """Extract rd.npz artifacts for every discovered session manifest."""
    manifest_results: list[RdExtractManifestResult] = []
    for manifest_path in _discover_manifest_paths(sessions_root=sessions_root):
        try:
            written_paths = extract_manifest_samples(
                manifest_path=manifest_path,
                overwrite=overwrite,
            )
        except Exception as exc:  # noqa: BLE001
            manifest_results.append(
                RdExtractManifestResult(
                    manifest_path=manifest_path,
                    written_paths=(),
                    error=str(exc),
                )
            )
        else:
            manifest_results.append(
                RdExtractManifestResult(
                    manifest_path=manifest_path,
                    written_paths=written_paths,
                    error=None,
                )
            )

    return RdExtractAllRunResult(manifest_results=tuple(manifest_results))


def write_rd_npz(
    *,
    sample: NpzSample,
    output_path: Path,
    overwrite: bool = False,
) -> Path:
    """Write one canonical rd.npz sample to a compressed NumPy archive."""
    resolved_output_path = output_path.expanduser().resolve()
    if resolved_output_path.exists() and not overwrite:
        msg = f"Output already exists: {resolved_output_path}"
        raise RdArtifactExistsError(msg)

    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, Any] = sample.as_arrays()
    np.savez_compressed(resolved_output_path, **arrays)
    return resolved_output_path


def extract_manifest_samples(
    *,
    manifest_path: Path,
    take_id: str | None = None,
    output_path: Path | None = None,
    overwrite: bool = False,
) -> tuple[Path, ...]:
    """Extract rd.npz for one or more accepted takes listed in one manifest."""
    resolved_manifest_path = resolve_repo_path(manifest_path)
    manifest = collection_session.load_manifest(resolved_manifest_path)
    collection_type = _require_str(manifest, "collection_type")
    firmware_config_id = _require_str(manifest, "firmware_config_id")
    config_path = mmwave_config.get_known_config(firmware_config_id).path.resolve()
    if collection_type == collection_session.COLLECTION_TYPE_GESTURE:
        return _extract_gesture_manifest_samples(
            manifest=manifest,
            config_path=config_path,
            take_id=take_id,
            output_path=output_path,
            overwrite=overwrite,
        )
    if collection_type in {
        collection_session.COLLECTION_TYPE_NORMAL_ACTIVITY,
        collection_session.COLLECTION_TYPE_WHITE_SPACE,
    }:
        if take_id is not None:
            msg = "Background manifests do not support --take-id extraction."
            raise ValueError(msg)
        if output_path is not None:
            msg = "Background manifests do not support --output."
            raise ValueError(msg)
        return _extract_background_manifest_samples(
            manifest_path=resolved_manifest_path,
            manifest=manifest,
            config_path=config_path,
            overwrite=overwrite,
        )

    msg = f"Unsupported collection_type for RD extraction: {collection_type!r}"
    raise ValueError(msg)


def _extract_gesture_manifest_samples(
    *,
    manifest: JsonObject,
    config_path: Path,
    take_id: str | None,
    output_path: Path | None,
    overwrite: bool,
) -> tuple[Path, ...]:
    """Extract canonical rd.npz artifacts for accepted gesture takes."""
    if output_path is not None and take_id is None:
        msg = (
            "--output requires --take-id because batch extraction writes "
            "one file per take."
        )
        raise ValueError(msg)

    resolved_takes = _select_manifest_takes(manifest=manifest, take_id=take_id)
    if not resolved_takes:
        return ()

    written_paths: list[Path] = []
    for take in resolved_takes:
        raw_uart_path = resolve_repo_path(_require_str(take, "raw_uart_path"))
        capture = extract_rd_capture(
            input_path=raw_uart_path,
            config_path=config_path,
        )
        sample = build_rd_npz_sample(
            capture=capture,
            manifest=manifest,
            take=take,
        )
        target_output_path = (
            output_path.expanduser().resolve()
            if output_path is not None
            else default_rd_output_path_for_capture(raw_uart_path)
        )
        written_paths.append(
            write_rd_npz(
                sample=sample,
                output_path=target_output_path,
                overwrite=overwrite,
            ),
        )

    return tuple(written_paths)


def _extract_background_manifest_samples(
    *,
    manifest_path: Path,
    manifest: JsonObject,
    config_path: Path,
    overwrite: bool,
) -> tuple[Path, ...]:
    """Extract seeded random background windows directly to rd.npz artifacts."""
    raw_uart_path = _resolve_background_raw_uart_path(manifest)
    capture = extract_rd_capture(
        input_path=raw_uart_path,
        config_path=config_path,
    )
    selection = _select_background_windows(
        capture=capture,
        manifest=manifest,
    )
    output_paths = tuple(
        default_background_segment_output_path(
            manifest_path=manifest_path,
            segment_id=window.segment_id,
        )
        for window in selection.selected_windows
    )
    index_path = default_background_segment_index_path(manifest_path=manifest_path)
    _ensure_outputs_available(
        paths=(*output_paths, index_path),
        overwrite=overwrite,
    )

    segment_records: list[BackgroundRdSegmentRecord] = []
    written_paths: list[Path] = []
    for selected_window, target_output_path in zip(
        selection.selected_windows,
        output_paths,
        strict=True,
    ):
        sample = build_background_rd_npz_sample(
            capture=capture,
            manifest=manifest,
            selected_window=selected_window,
        )
        written_paths.append(
            write_rd_npz(
                sample=sample,
                output_path=target_output_path,
                overwrite=overwrite,
            ),
        )
        segment_records.append(
            BackgroundRdSegmentRecord(
                segment_id=selected_window.segment_id,
                window_index=selected_window.window_index,
                start_frame_index=selected_window.start_frame_index,
                end_frame_index=selected_window.end_frame_index,
                capture_window_s=selected_window.capture_window_s,
                rd_npz_path=to_repo_relative_path(target_output_path),
            )
        )

    index = BackgroundRdSegmentIndex(
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
    _write_background_segment_index(
        index=index,
        output_path=index_path,
    )
    return tuple(written_paths)


def build_rd_npz_sample(
    *,
    capture: ExtractedRdCapture,
    manifest: JsonObject,
    take: JsonObject,
) -> RdNpzSample:
    """Build one canonical rd.npz sample from one extracted capture and manifest."""
    return RdNpzSample(
        rd_u16=capture.rd_cube_u16,
        capture_window_s=_window_to_tuple(_load_window(take, "capture_window")),
        target_window_s=_window_to_tuple(_load_window(take, "target_window")),
        marked_window_s=_optional_window_to_tuple(
            _load_optional_window(take, "marked_window")
        ),
        gesture=_require_str(manifest, "gesture"),
        subject_name=_require_str(manifest, "subject_name"),
        hand=_require_str(manifest, "hand"),
        distance_m=_optional_float(manifest.get("distance_m")),
        angle_deg=_optional_float(manifest.get("angle_deg")),
        environment=_require_str(manifest, "environment"),
        radar_id=_require_str(manifest, "radar_id"),
        firmware_id=_require_str(manifest, "firmware_id"),
        firmware_config_id=_require_str(manifest, "firmware_config_id"),
        session_id=_require_str(manifest, "session_id"),
        take_id=_require_str(take, "take_id"),
    )


def build_background_rd_npz_sample(
    *,
    capture: ExtractedRdCapture,
    manifest: JsonObject,
    selected_window: _SelectedBackgroundWindow,
) -> BackgroundRdNpzSample:
    """Build one background rd.npz sample from a selected slice window."""
    return BackgroundRdNpzSample(
        rd_u16=np.array(
            capture.rd_cube_u16[
                selected_window.start_frame_index : selected_window.end_frame_index
            ],
            dtype=np.uint16,
            copy=True,
        ),
        capture_window_s=selected_window.capture_window_s,
        collection_type=_require_str(manifest, "collection_type"),
        subject_name=_require_str(manifest, "subject_name"),
        hand=_require_str(manifest, "hand"),
        distance_m=_optional_float(manifest.get("distance_m")),
        angle_deg=_optional_float(manifest.get("angle_deg")),
        environment=_require_str(manifest, "environment"),
        radar_id=_require_str(manifest, "radar_id"),
        firmware_id=_require_str(manifest, "firmware_id"),
        firmware_config_id=_require_str(manifest, "firmware_config_id"),
        session_id=_require_str(manifest, "session_id"),
        segment_id=selected_window.segment_id,
    )


def default_rd_output_path_for_capture(input_path: Path) -> Path:
    """Resolve the default rd.npz path for one raw_uart.bin file."""
    return input_path.expanduser().resolve().with_name(DEFAULT_RD_ARTIFACT_FILENAME)


def default_background_segment_output_path(
    *,
    manifest_path: Path,
    segment_id: str,
) -> Path:
    """Resolve the default rd.npz path for one selected background segment."""
    return (
        manifest_path.expanduser().resolve().parent
        / "background"
        / DEFAULT_BACKGROUND_SEGMENTS_DIRNAME
        / segment_id
        / DEFAULT_RD_ARTIFACT_FILENAME
    )


def default_background_segment_index_path(*, manifest_path: Path) -> Path:
    """Resolve the default index/manifest path for background rd slices."""
    return (
        manifest_path.expanduser().resolve().parent
        / "background"
        / DEFAULT_BACKGROUND_SEGMENT_INDEX_FILENAME
    )


def format_extract_summary(
    *,
    output_path: Path,
    sample: RdNpzSample,
) -> str:
    """Render a short human-readable summary for one written artifact."""
    lines = [
        "RD extract summary",
        f"  output_path: {output_path}",
        f"  take_id: {sample.take_id}",
        f"  frame_count: {sample.rd_u16.shape[0]}",
        "  rd_shape: "
        f"({sample.rd_u16.shape[0]}, {sample.rd_u16.shape[1]}, "
        f"{sample.rd_u16.shape[2]})",
    ]
    return "\n".join(lines)


def _select_background_windows(
    *,
    capture: ExtractedRdCapture,
    manifest: JsonObject,
) -> _BackgroundWindowSelection:
    """Resolve the seeded random fixed windows selected from one background run."""
    background_plan = _require_dict(manifest, "background_plan")
    window_duration_s = _require_positive_float(background_plan, "window_duration_s")
    target_segment_count = _require_positive_int(
        background_plan,
        "target_segment_count",
    )
    selection_seed = _require_non_negative_int(background_plan, "selection_seed")
    selection_policy = _require_str(background_plan, "selection_policy")
    save_policy = _require_str(background_plan, "save_policy")
    if (
        selection_policy
        != collection_session.BACKGROUND_SELECTION_POLICY_RANDOM_AFTER_CAPTURE
    ):
        msg = (
            "Unsupported background selection_policy for RD extraction: "
            f"{selection_policy!r}"
        )
        raise ValueError(msg)
    if save_policy != collection_session.BACKGROUND_SAVE_POLICY_KEEP_FULL_CAPTURE:
        msg = f"Unsupported background save_policy for RD extraction: {save_policy!r}"
        raise ValueError(msg)

    frame_period_s = capture.config.frame_period_s
    frames_per_window = _resolve_frames_per_window(
        window_duration_s=window_duration_s,
        frame_period_s=frame_period_s,
    )
    candidate_window_count = capture.frame_count // frames_per_window
    if candidate_window_count < target_segment_count:
        msg = (
            "Background capture does not contain enough full windows for the "
            "planned random selection: "
            f"{candidate_window_count} < {target_segment_count}"
        )
        raise ValueError(msg)

    rng = random.Random(selection_seed)  # noqa: S311 - deterministic slicing is required here.
    selected_indices = sorted(
        rng.sample(
            range(candidate_window_count),
            target_segment_count,
        )
    )
    selected_windows = tuple(
        _SelectedBackgroundWindow(
            segment_id=f"segment{offset:04d}",
            window_index=window_index,
            start_frame_index=window_index * frames_per_window,
            end_frame_index=(window_index + 1) * frames_per_window,
            capture_window_s=(
                window_index * window_duration_s,
                (window_index + 1) * window_duration_s,
            ),
        )
        for offset, window_index in enumerate(selected_indices, start=1)
    )
    return _BackgroundWindowSelection(
        window_duration_s=window_duration_s,
        target_segment_count=target_segment_count,
        selection_seed=selection_seed,
        frame_period_s=frame_period_s,
        frames_per_window=frames_per_window,
        candidate_window_count=candidate_window_count,
        selected_windows=selected_windows,
    )


def _resolve_frames_per_window(
    *,
    window_duration_s: float,
    frame_period_s: float,
) -> int:
    """Convert one fixed window duration to an exact frame count."""
    ratio = window_duration_s / frame_period_s
    rounded_ratio = round(ratio)
    if rounded_ratio <= 0 or not math.isclose(
        ratio,
        rounded_ratio,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        msg = (
            "window_duration_s must map to an integral frame count for background "
            f"RD slicing ({window_duration_s} / {frame_period_s} = {ratio})."
        )
        raise ValueError(msg)
    return int(rounded_ratio)


def _resolve_background_raw_uart_path(manifest: JsonObject) -> Path:
    """Resolve the completed continuous raw capture recorded by a background session."""
    background_capture = _require_dict(manifest, "background_capture")
    status = _require_str(background_capture, "status")
    if status != collection_session.BACKGROUND_CAPTURE_STATUS_COMPLETED:
        msg = "Background RD extraction requires background_capture.status='completed'."
        raise ValueError(msg)
    return resolve_repo_path(_require_str(background_capture, "raw_uart_path"))


def _write_background_segment_index(
    *,
    index: BackgroundRdSegmentIndex,
    output_path: Path,
) -> Path:
    """Write one background slice index/manifest with stable JSON formatting."""
    resolved_output_path = output_path.expanduser().resolve()
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_text(
        json.dumps(index.as_dict(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return resolved_output_path


def _ensure_outputs_available(*, paths: tuple[Path, ...], overwrite: bool) -> None:
    """Fail early when any extraction output already exists."""
    if overwrite:
        return
    for path in paths:
        resolved_path = path.expanduser().resolve()
        if resolved_path.exists():
            msg = f"Output already exists: {resolved_path}"
            raise RdArtifactExistsError(msg)


def _select_manifest_takes(
    *,
    manifest: JsonObject,
    take_id: str | None,
) -> tuple[JsonObject, ...]:
    """Resolve the accepted takes targeted by one extraction request."""
    raw_takes = manifest.get("takes")
    if not isinstance(raw_takes, list):
        msg = "manifest field 'takes' must be a list."
        raise TypeError(msg)

    take_objects = tuple(take for take in raw_takes if isinstance(take, dict))
    if take_id is None:
        return tuple(
            take
            for take in take_objects
            if take.get("status") == collection_session.TAKE_STATUS_ACCEPTED
        )

    for take in take_objects:
        if take.get("take_id") != take_id:
            continue
        if take.get("status") != collection_session.TAKE_STATUS_ACCEPTED:
            msg = f"take {take_id!r} is not accepted and cannot be extracted."
            raise ValueError(msg)
        return (take,)

    msg = f"take {take_id!r} was not found in the manifest."
    raise KeyError(msg)


def _require_dict(data: JsonObject, key: str) -> JsonObject:
    """Require one object field from a JSON-like mapping."""
    value = data.get(key)
    if isinstance(value, dict):
        return value

    msg = f"Field {key!r} must be an object."
    raise TypeError(msg)


def _require_str(data: JsonObject, key: str) -> str:
    """Require one non-empty string field from a JSON-like mapping."""
    value = data.get(key)
    if isinstance(value, str) and value:
        return value

    msg = f"Field {key!r} must be a non-empty string."
    raise ValueError(msg)


def _optional_float(value: object) -> float | None:
    """Return one numeric metadata value or None."""
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)

    msg = "Optional numeric metadata fields must be int, float, or null."
    raise TypeError(msg)


def _require_positive_float(data: JsonObject, key: str) -> float:
    """Require one positive numeric field from a JSON-like mapping."""
    value = data.get(key)
    if _is_number(value) and value > 0:
        return float(value)

    msg = f"Field {key!r} must be a positive number."
    raise ValueError(msg)


def _require_positive_int(data: JsonObject, key: str) -> int:
    """Require one positive integer field from a JSON-like mapping."""
    value = data.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value

    msg = f"Field {key!r} must be a positive integer."
    raise ValueError(msg)


def _require_non_negative_int(data: JsonObject, key: str) -> int:
    """Require one non-negative integer field from a JSON-like mapping."""
    value = data.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value

    msg = f"Field {key!r} must be a non-negative integer."
    raise ValueError(msg)


def _load_window(data: JsonObject, field_name: str) -> WindowRange:
    """Load one required window from a take mapping."""
    raw_value = data.get(field_name)
    if not isinstance(raw_value, dict):
        msg = f"Field {field_name!r} must be a window object."
        raise TypeError(msg)
    window_data = raw_value
    start_s = window_data.get("start_s")
    end_s = window_data.get("end_s")
    if not _is_number(start_s) or not _is_number(end_s):
        msg = f"Field {field_name!r} must contain numeric start_s/end_s."
        raise ValueError(msg)
    if end_s < start_s:
        msg = f"Field {field_name!r} must satisfy end_s >= start_s."
        raise ValueError(msg)
    return WindowRange(start_s=float(start_s), end_s=float(end_s))


def _load_optional_window(data: JsonObject, field_name: str) -> WindowRange | None:
    """Load one optional window from a take mapping."""
    raw_value = data.get(field_name)
    if raw_value is None:
        return None
    if not isinstance(raw_value, dict):
        msg = f"Field {field_name!r} must be a window object or null."
        raise TypeError(msg)
    window_data = raw_value
    start_s = window_data.get("start_s")
    end_s = window_data.get("end_s")
    if not _is_number(start_s) or not _is_number(end_s):
        msg = f"Field {field_name!r} must contain numeric start_s/end_s."
        raise ValueError(msg)
    if end_s < start_s:
        msg = f"Field {field_name!r} must satisfy end_s >= start_s."
        raise ValueError(msg)
    return WindowRange(start_s=float(start_s), end_s=float(end_s))


def _window_to_tuple(window: WindowRange) -> tuple[float, float]:
    """Convert one window object to the canonical tuple form."""
    return (window.start_s, window.end_s)


def _optional_window_to_tuple(
    window: WindowRange | None,
) -> tuple[float, float] | None:
    """Convert one optional window object to the canonical tuple form."""
    if window is None:
        return None
    return _window_to_tuple(window)


def _is_number(value: object) -> TypeGuard[int | float]:
    """Return whether one JSON-like value is numeric but not bool."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _discover_manifest_paths(*, sessions_root: str | Path) -> tuple[Path, ...]:
    resolved_sessions_root = resolve_repo_path(sessions_root)
    if not resolved_sessions_root.exists():
        return ()
    return tuple(
        sorted(resolved_sessions_root.glob(f"*/{collection_session.MANIFEST_FILENAME}"))
    )
