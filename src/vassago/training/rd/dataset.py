"""RD dataset discovery, labeling, splitting, and NumPy preprocessing helpers."""

from __future__ import annotations

from dataclasses import dataclass
import random
from pathlib import Path

import numpy as np

from vassago.training.rd.config import LabelMode

DETECTION_POSITIVE_LABEL = "gesture"
DETECTION_NEGATIVE_LABEL = "non_gesture"
DETECTION_NEGATIVE_COLLECTION_TYPES = frozenset({"white_space", "normal_activity"})


@dataclass(slots=True, frozen=True)
class TrainingSample:
    """One discovered `rd.npz` sample with resolved metadata for training."""

    path: Path
    label: str
    subject_name: str


@dataclass(slots=True, frozen=True)
class DatasetScanResult:
    """The discovered sample set and its sorted label vocabulary."""

    samples: tuple[TrainingSample, ...]
    labels: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class DatasetSplit:
    """One train/validation split over discovered training samples."""

    train_samples: tuple[TrainingSample, ...]
    val_samples: tuple[TrainingSample, ...]


def discover_training_samples(
    *,
    data_root: Path,
    allowed_labels: tuple[str, ...],
    label_mode: LabelMode,
) -> DatasetScanResult:
    """Discover all labeled `rd.npz` samples under one data root."""
    resolved_root = data_root.expanduser().resolve()
    if not resolved_root.exists():
        msg = f"Data root does not exist: {resolved_root}"
        raise FileNotFoundError(msg)

    allowed_label_set = set(allowed_labels)
    samples: list[TrainingSample] = []
    for npz_path in sorted(resolved_root.glob("**/rd.npz")):
        sample = _load_training_sample(
            npz_path=npz_path,
            allowed_labels=allowed_label_set,
            label_mode=label_mode,
        )
        if sample is not None:
            samples.append(sample)

    if not samples:
        msg = (
            "No labeled rd.npz samples were discovered. "
            "Check the data root and allowed labels."
        )
        raise ValueError(msg)

    labels = tuple(sorted({sample.label for sample in samples}))
    return DatasetScanResult(samples=tuple(samples), labels=labels)


def split_dataset(
    *,
    samples: tuple[TrainingSample, ...],
    val_ratio: float,
    seed: int,
) -> DatasetSplit:
    """Build a stratified train/validation split from discovered samples."""
    if not 0.0 < val_ratio < 1.0:
        msg = "val_ratio must be between 0 and 1."
        raise ValueError(msg)

    by_label: dict[str, list[TrainingSample]] = {}
    for sample in samples:
        by_label.setdefault(sample.label, []).append(sample)

    rng = random.Random(seed)
    train_samples: list[TrainingSample] = []
    val_samples: list[TrainingSample] = []
    for label_samples in by_label.values():
        shuffled = list(label_samples)
        rng.shuffle(shuffled)
        if len(shuffled) == 1:
            train_samples.extend(shuffled)
            continue

        val_count = max(1, round(len(shuffled) * val_ratio))
        if val_count >= len(shuffled):
            val_count = len(shuffled) - 1
        val_samples.extend(shuffled[:val_count])
        train_samples.extend(shuffled[val_count:])

    if not train_samples or not val_samples:
        msg = "Unable to build a non-empty train/validation split from the dataset."
        raise ValueError(msg)

    return DatasetSplit(
        train_samples=tuple(train_samples),
        val_samples=tuple(val_samples),
    )


def load_rd_tensor(
    *,
    npz_path: Path,
    target_frames: int,
    normalize: bool,
) -> np.ndarray:
    """Load one `rd` tensor and align its frame count to `target_frames`."""
    if target_frames <= 0:
        msg = "target_frames must be positive."
        raise ValueError(msg)

    with np.load(npz_path, allow_pickle=False) as npz:
        if "rd" not in npz:
            msg = f"Missing 'rd' in npz: {npz_path}"
            raise KeyError(msg)
        rd = np.asarray(npz["rd"], dtype=np.float32)

    if rd.ndim != 3:
        msg = f"Expected an RD tensor shaped (T, R, D), got {rd.shape}"
        raise ValueError(msg)

    aligned = _resample_frame_count(rd=rd, target_frames=target_frames)
    if not normalize:
        return aligned

    mean = float(np.mean(aligned))
    std = float(np.std(aligned))
    if std <= 1e-6:
        return aligned - mean
    return (aligned - mean) / std


def _load_training_sample(
    *,
    npz_path: Path,
    allowed_labels: set[str],
    label_mode: LabelMode,
) -> TrainingSample | None:
    """Load one `TrainingSample` from a canonical `rd.npz` file."""
    with np.load(npz_path, allow_pickle=False) as npz:
        label = _resolve_label(npz=npz, label_mode=label_mode)
        if label is None or label not in allowed_labels:
            return None
        subject_name = _read_optional_scalar_str(npz=npz, key="subject_name") or "unknown"

    return TrainingSample(path=npz_path, label=label, subject_name=subject_name)


def _resolve_label(
    *,
    npz: np.lib.npyio.NpzFile,
    label_mode: LabelMode,
) -> str | None:
    """Resolve the class label from one canonical `rd.npz` archive."""
    gesture = _read_optional_scalar_str(npz=npz, key="gesture")
    collection_type = _read_optional_scalar_str(npz=npz, key="collection_type")

    if label_mode == "gesture":
        return gesture
    if label_mode == "collection":
        return collection_type
    if label_mode == "auto":
        return gesture if gesture is not None else collection_type
    if label_mode == "detection":
        if gesture is not None:
            return DETECTION_POSITIVE_LABEL
        if collection_type in DETECTION_NEGATIVE_COLLECTION_TYPES:
            return DETECTION_NEGATIVE_LABEL
        return None

    msg = f"Unsupported label_mode: {label_mode!r}"
    raise ValueError(msg)


def _resample_frame_count(*, rd: np.ndarray, target_frames: int) -> np.ndarray:
    """Align the time dimension to a fixed frame count via nearest resampling."""
    if rd.shape[0] == target_frames:
        return rd

    frame_indices = np.linspace(
        0,
        rd.shape[0] - 1,
        num=target_frames,
        dtype=np.float64,
    )
    nearest_indices = np.rint(frame_indices).astype(np.int64)
    return rd[nearest_indices, :, :]


def _read_optional_scalar_str(*, npz: np.lib.npyio.NpzFile, key: str) -> str | None:
    """Read one optional scalar string field from a NumPy archive."""
    if key not in npz:
        return None

    raw_value = np.asarray(npz[key])
    if raw_value.size != 1:
        return None
    scalar = raw_value.item()
    if isinstance(scalar, bytes):
        decoded = scalar.decode("utf-8", errors="ignore").strip()
        return decoded if decoded else None
    if isinstance(scalar, str):
        stripped = scalar.strip()
        return stripped if stripped else None
    return None
