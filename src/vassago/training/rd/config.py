"""Typed configuration models for RD detector/classifier training runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ModelName = Literal["2d_cnn_tcn", "3d_cnn"]
TaskName = Literal["detector", "classifier"]
LabelMode = Literal["gesture", "collection", "auto", "detection"]


@dataclass(slots=True, frozen=True)
class TrainingRunConfig:
    """One immutable training-run configuration."""

    task_name: TaskName
    model_name: ModelName
    data_root: Path
    output_root: Path
    allowed_labels: tuple[str, ...]
    label_mode: LabelMode
    target_frames: int
    batch_size: int
    epochs: int
    learning_rate: float
    min_learning_rate: float
    weight_decay: float
    val_ratio: float
    early_stopping_patience: int
    early_stopping_min_delta: float
    seed: int
    normalize: bool
    device: str | None = None
