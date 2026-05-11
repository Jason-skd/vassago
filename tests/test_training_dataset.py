"""Tests for RD training dataset discovery and preprocessing."""

from __future__ import annotations

import numpy as np

from vassago.training.rd.dataset import discover_training_samples
from vassago.training.rd.dataset import load_rd_tensor
from vassago.training.rd.dataset import split_dataset


def test_discover_training_samples_filters_to_allowed_gesture_labels(tmp_path) -> None:
    gesture_path = tmp_path / "gesture" / "rd.npz"
    gesture_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        gesture_path,
        rd=np.ones((6, 8, 4), dtype=np.uint16),
        gesture=np.asarray("wave"),
        subject_name=np.asarray("alice"),
    )

    background_path = tmp_path / "background" / "rd.npz"
    background_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        background_path,
        rd=np.ones((6, 8, 4), dtype=np.uint16),
        collection_type=np.asarray("white_space"),
        subject_name=np.asarray("alice"),
    )

    scan_result = discover_training_samples(
        data_root=tmp_path,
        allowed_labels=("wave", "flip"),
        label_mode="gesture",
    )

    assert scan_result.labels == ("wave",)
    assert len(scan_result.samples) == 1
    assert scan_result.samples[0].label == "wave"


def test_discover_training_samples_builds_detector_labels_from_mixed_samples(
    tmp_path,
) -> None:
    gesture_path = tmp_path / "gesture" / "rd.npz"
    gesture_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        gesture_path,
        rd=np.ones((6, 8, 4), dtype=np.uint16),
        gesture=np.asarray("flip"),
        subject_name=np.asarray("alice"),
    )

    normal_activity_path = tmp_path / "normal_activity" / "rd.npz"
    normal_activity_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        normal_activity_path,
        rd=np.ones((6, 8, 4), dtype=np.uint16),
        collection_type=np.asarray("normal_activity"),
        subject_name=np.asarray("bob"),
    )

    scan_result = discover_training_samples(
        data_root=tmp_path,
        allowed_labels=("gesture", "non_gesture"),
        label_mode="detection",
    )

    assert scan_result.labels == ("gesture", "non_gesture")
    assert {sample.label for sample in scan_result.samples} == {
        "gesture",
        "non_gesture",
    }


def test_split_dataset_creates_non_empty_train_and_validation_sets() -> None:
    samples_root = []
    for index in range(6):
        label = "wave" if index < 3 else "flip"
        samples_root.append(
            type(
                "Sample",
                (),
                {
                    "path": None,
                    "label": label,
                    "subject_name": "subject",
                    "session_id": f"session_{index // 2}",
                },
            )()
        )

    split = split_dataset(
        samples=tuple(samples_root),
        val_ratio=0.33,
        seed=7,
        group_by="session",
    )

    assert split.train_samples
    assert split.val_samples
    assert {sample.label for sample in split.train_samples} == {"wave", "flip"}
    assert {sample.label for sample in split.val_samples} == {"wave", "flip"}


def test_load_rd_tensor_resamples_and_normalizes_one_clip(tmp_path) -> None:
    sample_path = tmp_path / "sample" / "rd.npz"
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    rd = np.arange(4 * 8 * 4, dtype=np.uint16).reshape(4, 8, 4)
    np.savez_compressed(
        sample_path,
        rd=rd,
        gesture=np.asarray("wave"),
        subject_name=np.asarray("alice"),
    )

    loaded = load_rd_tensor(
        npz_path=sample_path,
        target_frames=6,
        normalize=True,
        use_active_window=False,
        active_window_context_frames=0,
    )

    assert loaded.shape == (6, 8, 4)
    assert np.isclose(float(np.mean(loaded)), 0.0, atol=1e-5)


def test_load_rd_tensor_crops_marked_window_before_resample(tmp_path) -> None:
    sample_path = tmp_path / "sample_windowed" / "rd.npz"
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    rd = np.arange(10 * 2 * 2, dtype=np.uint16).reshape(10, 2, 2)
    np.savez_compressed(
        sample_path,
        rd=rd,
        capture_window_s=np.asarray((0.0, 10.0), dtype=np.float32),
        target_window_s=np.asarray((2.0, 8.0), dtype=np.float32),
        marked_window_s=np.asarray((4.0, 6.0), dtype=np.float32),
        gesture=np.asarray("wave"),
        subject_name=np.asarray("alice"),
    )

    loaded = load_rd_tensor(
        npz_path=sample_path,
        target_frames=2,
        normalize=False,
        use_active_window=True,
        active_window_context_frames=0,
    )

    assert loaded.shape == (2, 2, 2)
    assert int(loaded[0, 0, 0]) == int(rd[4, 0, 0])
    assert int(loaded[-1, 0, 0]) == int(rd[5, 0, 0])
