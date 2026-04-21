"""Typed models for extracted RD captures and canonical rd.npz samples."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from pathlib import Path

    from vassago.processing.mmwave.config import MmwaveProcessingConfig

type UInt16Array = npt.NDArray[np.uint16]

RD_NPZ_SCHEMA_VERSION = "rd_npz_v1"
BACKGROUND_RD_NPZ_SCHEMA_VERSION = "rd_background_npz_v1"
BACKGROUND_RD_SEGMENT_INDEX_SCHEMA_VERSION = "rd_background_segment_index_v1"


@dataclass(slots=True, frozen=True)
class ExtractedRdCapture:
    """One strictly extracted RD capture ready for canonical packaging."""

    source_path: Path
    config: MmwaveProcessingConfig
    rd_cube_u16: UInt16Array

    @property
    def frame_count(self) -> int:
        """Return the number of extracted RD frames."""
        return int(self.rd_cube_u16.shape[0])


@dataclass(slots=True, frozen=True)
class RdNpzSample:
    """One canonical rd.npz sample with training-facing metadata."""

    rd_u16: UInt16Array
    capture_window_s: tuple[float, float]
    target_window_s: tuple[float, float]
    marked_window_s: tuple[float, float] | None
    gesture: str
    subject_name: str
    hand: str
    distance_m: float | None
    angle_deg: float | None
    environment: str
    radar_id: str
    firmware_id: str
    firmware_config_id: str
    session_id: str
    take_id: str
    schema_version: str = RD_NPZ_SCHEMA_VERSION

    def as_arrays(self) -> dict[str, np.ndarray]:
        """Convert the canonical sample into savez-ready NumPy arrays."""
        marked_window = (
            np.asarray(self.marked_window_s, dtype=np.float32)
            if self.marked_window_s is not None
            else np.asarray((np.nan, np.nan), dtype=np.float32)
        )
        return {
            "schema_version": np.asarray(self.schema_version),
            "rd": self.rd_u16,
            "capture_window_s": np.asarray(self.capture_window_s, dtype=np.float32),
            "target_window_s": np.asarray(self.target_window_s, dtype=np.float32),
            "marked_window_s": marked_window,
            "gesture": np.asarray(self.gesture),
            "subject_name": np.asarray(self.subject_name),
            "hand": np.asarray(self.hand),
            "distance_m": np.asarray(_float_or_nan(self.distance_m), dtype=np.float32),
            "angle_deg": np.asarray(_float_or_nan(self.angle_deg), dtype=np.float32),
            "environment": np.asarray(self.environment),
            "radar_id": np.asarray(self.radar_id),
            "firmware_id": np.asarray(self.firmware_id),
            "firmware_config_id": np.asarray(self.firmware_config_id),
            "session_id": np.asarray(self.session_id),
            "take_id": np.asarray(self.take_id),
        }


def _float_or_nan(value: float | None) -> float:
    """Return one finite float value or NaN for optional numeric metadata."""
    return float(value) if value is not None else float("nan")


@dataclass(slots=True, frozen=True)
class BackgroundRdNpzSample:
    """One canonical background rd.npz sample derived from a slice window."""

    rd_u16: UInt16Array
    capture_window_s: tuple[float, float]
    collection_type: str
    subject_name: str
    hand: str
    distance_m: float | None
    angle_deg: float | None
    environment: str
    radar_id: str
    firmware_id: str
    firmware_config_id: str
    session_id: str
    segment_id: str
    schema_version: str = BACKGROUND_RD_NPZ_SCHEMA_VERSION

    def as_arrays(self) -> dict[str, np.ndarray]:
        """Convert one background sample into savez-ready NumPy arrays."""
        return {
            "schema_version": np.asarray(self.schema_version),
            "rd": self.rd_u16,
            "capture_window_s": np.asarray(self.capture_window_s, dtype=np.float32),
            "collection_type": np.asarray(self.collection_type),
            "subject_name": np.asarray(self.subject_name),
            "hand": np.asarray(self.hand),
            "distance_m": np.asarray(_float_or_nan(self.distance_m), dtype=np.float32),
            "angle_deg": np.asarray(_float_or_nan(self.angle_deg), dtype=np.float32),
            "environment": np.asarray(self.environment),
            "radar_id": np.asarray(self.radar_id),
            "firmware_id": np.asarray(self.firmware_id),
            "firmware_config_id": np.asarray(self.firmware_config_id),
            "session_id": np.asarray(self.session_id),
            "segment_id": np.asarray(self.segment_id),
        }


@dataclass(slots=True, frozen=True)
class BackgroundRdSegmentRecord:
    """One selected background slice and its written artifact path."""

    segment_id: str
    window_index: int
    start_frame_index: int
    end_frame_index: int
    capture_window_s: tuple[float, float]
    rd_npz_path: str

    def as_dict(self) -> dict[str, object]:
        """Convert the segment record to a JSON-ready mapping."""
        return {
            "segment_id": self.segment_id,
            "window_index": self.window_index,
            "start_frame_index": self.start_frame_index,
            "end_frame_index": self.end_frame_index,
            "capture_window": {
                "start_s": self.capture_window_s[0],
                "end_s": self.capture_window_s[1],
            },
            "rd_npz_path": self.rd_npz_path,
        }


@dataclass(slots=True, frozen=True)
class BackgroundRdSegmentIndex:
    """Persisted index/manifest for one background slicing run."""

    session_id: str
    collection_type: str
    source_raw_uart_path: str
    window_duration_s: float
    target_segment_count: int
    selection_seed: int
    frame_period_s: float
    frames_per_window: int
    total_frame_count: int
    candidate_window_count: int
    segments: tuple[BackgroundRdSegmentRecord, ...]
    schema_version: str = BACKGROUND_RD_SEGMENT_INDEX_SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        """Convert the index to a JSON-ready mapping."""
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "collection_type": self.collection_type,
            "source_raw_uart_path": self.source_raw_uart_path,
            "window_duration_s": self.window_duration_s,
            "target_segment_count": self.target_segment_count,
            "selection_seed": self.selection_seed,
            "frame_period_s": self.frame_period_s,
            "frames_per_window": self.frames_per_window,
            "total_frame_count": self.total_frame_count,
            "candidate_window_count": self.candidate_window_count,
            "segments": [segment.as_dict() for segment in self.segments],
        }
