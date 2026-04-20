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
