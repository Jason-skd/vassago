"""Canonical rd.npz artifact writing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any
from typing import TypeGuard

import numpy as np

from vassago.collection.rd import session as collection_session
from vassago.collection.rd.config import WindowRange
from vassago.collection.rd.paths import resolve_repo_path
from vassago.firmware.mmwave import config as mmwave_config
from vassago.processing.rd.extract import extract_rd_capture
from vassago.processing.rd.model import ExtractedRdCapture
from vassago.processing.rd.model import RdNpzSample

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_RD_ARTIFACT_FILENAME = "rd.npz"

type JsonObject = dict[str, object]


class RdArtifactExistsError(FileExistsError):
    """Raised when rd.npz already exists and overwrite is disabled."""


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
    sample: RdNpzSample,
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
    if output_path is not None and take_id is None:
        msg = (
            "--output requires --take-id because batch extraction writes "
            "one file per take."
        )
        raise ValueError(msg)

    resolved_manifest_path = resolve_repo_path(manifest_path)
    manifest = collection_session.load_manifest(resolved_manifest_path)
    resolved_takes = _select_manifest_takes(manifest=manifest, take_id=take_id)
    if not resolved_takes:
        return ()

    firmware_config_id = _require_str(manifest, "firmware_config_id")
    config_path = mmwave_config.get_known_config(firmware_config_id).path.resolve()
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


def default_rd_output_path_for_capture(input_path: Path) -> Path:
    """Resolve the default rd.npz path for one raw_uart.bin file."""
    return input_path.expanduser().resolve().with_name(DEFAULT_RD_ARTIFACT_FILENAME)


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
