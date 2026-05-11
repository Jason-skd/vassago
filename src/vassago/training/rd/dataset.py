"""RD dataset discovery, labeling, splitting, and NumPy preprocessing helpers."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from vassago.training.rd.config import LabelMode
from vassago.training.rd.config import SplitGroupBy

DETECTION_POSITIVE_LABEL = "gesture"
DETECTION_NEGATIVE_LABEL = "non_gesture"
DETECTION_NEGATIVE_COLLECTION_TYPES = frozenset({"white_space", "normal_activity"})


@dataclass(slots=True, frozen=True)
class TrainingSample:
    """One discovered `rd.npz` sample with resolved metadata for training."""

    path: Path
    label: str
    subject_name: str
    session_id: str


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
    group_by: SplitGroupBy,
) -> DatasetSplit:
    """Build a group-aware stratified train/validation split from discovered samples."""
    if not 0.0 < val_ratio < 1.0:
        msg = "val_ratio must be between 0 and 1."
        raise ValueError(msg)

    rng = random.Random(seed)
    group_to_samples: dict[str, list[TrainingSample]] = {}
    for sample in samples:
        group_key = _resolve_group_key(sample=sample, group_by=group_by)
        group_to_samples.setdefault(group_key, []).append(sample)

    group_keys = list(group_to_samples.keys())
    rng.shuffle(group_keys)

    label_totals: dict[str, int] = {}
    for sample in samples:
        label_totals[sample.label] = label_totals.get(sample.label, 0) + 1
    label_targets = {
        label: max(1, round(total_count * val_ratio))
        for label, total_count in label_totals.items()
        if total_count > 1
    }
    label_val_counts = dict.fromkeys(label_totals, 0)

    val_group_keys: set[str] = set()
    for label, target_count in label_targets.items():
        candidate_group_keys = [
            group_key
            for group_key in group_keys
            if any(sample.label == label for sample in group_to_samples[group_key])
        ]
        rng.shuffle(candidate_group_keys)
        for group_key in candidate_group_keys:
            if label_val_counts[label] >= target_count:
                break
            val_group_keys.add(group_key)
            for sample in group_to_samples[group_key]:
                label_val_counts[sample.label] += 1

    val_group_keys = _rebalance_group_split_for_label_coverage(
        samples=samples,
        group_to_samples=group_to_samples,
        val_group_keys=val_group_keys,
        rng=rng,
    )

    train_samples: list[TrainingSample] = []
    val_samples: list[TrainingSample] = []
    for group_key, grouped_samples in group_to_samples.items():
        if group_key in val_group_keys:
            val_samples.extend(grouped_samples)
        else:
            train_samples.extend(grouped_samples)

    if not train_samples:
        moved_group = next(iter(val_group_keys), None)
        if moved_group is None:
            msg = "Unable to build a non-empty train split from grouped samples."
            raise ValueError(msg)
        moved_samples = group_to_samples[moved_group]
        train_samples.extend(moved_samples)
        val_samples = [sample for sample in val_samples if sample not in moved_samples]
    if not val_samples:
        movable_group = next(
            (
                group_key
                for group_key in group_keys
                if group_key not in val_group_keys
                and len(group_to_samples[group_key]) < len(train_samples)
            ),
            None,
        )
        if movable_group is None:
            msg = "Unable to build a non-empty validation split from grouped samples."
            raise ValueError(msg)
        moved_samples = group_to_samples[movable_group]
        val_samples.extend(moved_samples)
        train_samples = [
            sample for sample in train_samples if sample not in moved_samples
        ]

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
    use_active_window: bool,
    active_window_context_frames: int,
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
        if use_active_window:
            rd = _crop_to_active_window(
                rd=rd,
                npz=npz,
                active_window_context_frames=active_window_context_frames,
            )

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
        subject_name = (
            _read_optional_scalar_str(npz=npz, key="subject_name") or "unknown"
        )
        session_id = _read_optional_scalar_str(npz=npz, key="session_id") or "unknown"

    return TrainingSample(
        path=npz_path,
        label=label,
        subject_name=subject_name,
        session_id=session_id,
    )


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
        return decoded or None
    if isinstance(scalar, str):
        stripped = scalar.strip()
        return stripped or None
    return None


def _resolve_group_key(*, sample: TrainingSample, group_by: SplitGroupBy) -> str:
    """Resolve the split group key for one training sample."""
    if group_by == "subject":
        return sample.subject_name
    if group_by == "session":
        return sample.session_id

    msg = f"Unsupported group_by: {group_by!r}"
    raise ValueError(msg)


def _rebalance_group_split_for_label_coverage(
    *,
    samples: tuple[TrainingSample, ...],
    group_to_samples: dict[str, list[TrainingSample]],
    val_group_keys: set[str],
    rng: random.Random,
) -> set[str]:
    """Ensure each label appears in both splits whenever multiple groups exist."""
    labels = sorted({sample.label for sample in samples})
    for label in labels:
        groups_with_label = [
            group_key
            for group_key, grouped_samples in group_to_samples.items()
            if any(sample.label == label for sample in grouped_samples)
        ]
        if len(groups_with_label) <= 1:
            continue

        val_groups = [
            group_key for group_key in groups_with_label if group_key in val_group_keys
        ]
        train_groups = [
            group_key
            for group_key in groups_with_label
            if group_key not in val_group_keys
        ]
        if not train_groups:
            movable = sorted(
                val_groups,
                key=lambda group_key: len(group_to_samples[group_key]),
            )
            if movable:
                val_group_keys.remove(movable[0])
        elif not val_groups:
            movable = sorted(
                train_groups,
                key=lambda group_key: len(group_to_samples[group_key]),
            )
            if movable:
                val_group_keys.add(movable[0])

    # Add small stochasticity so repeated runs with same seed can still be deterministic.
    normalized = list(val_group_keys)
    rng.shuffle(normalized)
    return set(normalized)


def _crop_to_active_window(
    *,
    rd: np.ndarray,
    npz: np.lib.npyio.NpzFile,
    active_window_context_frames: int,
) -> np.ndarray:
    """Crop one RD tensor to the active window before temporal resampling."""
    if rd.shape[0] <= 1:
        return rd

    capture_window_s = _read_optional_scalar_f32_pair(npz=npz, key="capture_window_s")
    if capture_window_s is None:
        return rd

    marked_window_s = _read_optional_scalar_f32_pair(npz=npz, key="marked_window_s")
    target_window_s = _read_optional_scalar_f32_pair(npz=npz, key="target_window_s")
    active_window_s = marked_window_s or target_window_s
    if active_window_s is None:
        return rd

    capture_start, capture_end = capture_window_s
    active_start, active_end = active_window_s
    if (
        capture_end <= capture_start
        or active_end <= active_start
        or active_end <= capture_start
        or active_start >= capture_end
    ):
        return rd

    frame_period_s = (capture_end - capture_start) / float(rd.shape[0])
    context_s = max(0, active_window_context_frames) * frame_period_s
    cropped_start_s = max(capture_start, active_start - context_s)
    cropped_end_s = min(capture_end, active_end + context_s)
    if cropped_end_s <= cropped_start_s:
        return rd

    start_index = int(np.floor((cropped_start_s - capture_start) / frame_period_s))
    end_index_exclusive = int(np.ceil((cropped_end_s - capture_start) / frame_period_s))
    start_index = max(0, min(start_index, rd.shape[0] - 1))
    end_index_exclusive = max(start_index + 1, min(end_index_exclusive, rd.shape[0]))
    return rd[start_index:end_index_exclusive, :, :]


def _read_optional_scalar_f32_pair(
    *,
    npz: np.lib.npyio.NpzFile,
    key: str,
) -> tuple[float, float] | None:
    """Read one optional float pair from a NumPy archive, ignoring NaN fields."""
    if key not in npz:
        return None

    raw_value = np.asarray(npz[key], dtype=np.float32).reshape(-1)
    if raw_value.size < 2:
        return None
    start = float(raw_value[0])
    end = float(raw_value[1])
    if not np.isfinite(start) or not np.isfinite(end):
        return None
    return (start, end)
