"""Typer command registration for RD model training workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from vassago.training.rd.config import TrainingRunConfig

console = Console()
DEFAULT_DATA_ROOT = Path("data/collection/rd/sessions")
DEFAULT_OUTPUT_ROOT = Path("artifacts/training/rd")
DEFAULT_CLASSIFIER_LABELS = "wave,circle_cw,flip"
DEFAULT_DETECTOR_LABELS = "gesture,non_gesture"


def register_commands(app: typer.Typer) -> None:
    """Attach RD training subcommands to an existing Typer app."""
    app.command("train-2d-cnn-tcn")(handle_train_2d_cnn_tcn)
    app.command("train-3d-cnn")(handle_train_3d_cnn)
    app.command("train-detector-2d-cnn-tcn")(handle_train_2d_cnn_tcn)
    app.command("train-classifier-3d-cnn")(handle_train_3d_cnn)


def handle_train_2d_cnn_tcn(
    data_root: Annotated[
        Path,
        typer.Option(help="Root directory scanned recursively for canonical rd.npz samples."),
    ] = DEFAULT_DATA_ROOT,
    output_root: Annotated[
        Path,
        typer.Option(help="Directory where checkpoints and metrics are written."),
    ] = DEFAULT_OUTPUT_ROOT,
    labels: Annotated[
        str,
        typer.Option(help="Comma-separated gesture labels used for classification."),
    ] = DEFAULT_DETECTOR_LABELS,
    epochs: Annotated[int, typer.Option(help="Number of training epochs.")] = 20,
    batch_size: Annotated[int, typer.Option(help="Mini-batch size.")] = 16,
    learning_rate: Annotated[float, typer.Option(help="Adam learning rate.")] = 1e-3,
    min_learning_rate: Annotated[
        float,
        typer.Option(help="Minimum learning rate for cosine annealing."),
    ] = 1e-6,
    weight_decay: Annotated[float, typer.Option(help="Adam weight decay.")] = 1e-4,
    early_stopping_patience: Annotated[
        int,
        typer.Option(help="Stop when val accuracy does not improve for N epochs."),
    ] = 5,
    early_stopping_min_delta: Annotated[
        float,
        typer.Option(help="Minimum val accuracy improvement to reset patience."),
    ] = 1e-4,
    target_frames: Annotated[
        int,
        typer.Option(help="Fixed frame count after temporal resampling."),
    ] = 50,
    val_ratio: Annotated[
        float,
        typer.Option(help="Validation split ratio, stratified by label."),
    ] = 0.2,
    seed: Annotated[int, typer.Option(help="Random seed used for split and training.")] = 7,
    normalize: Annotated[
        bool,
        typer.Option(
            "--normalize/--no-normalize",
            help="Apply per-sample z-score normalization before training.",
        ),
    ] = True,
    device: Annotated[
        str | None,
        typer.Option(help="Explicit torch device such as cpu, cuda, or mps."),
    ] = None,
) -> None:
    """Train the lightweight `2D CNN + TCN` RD gesture detector."""
    _run_training_command(
        config=TrainingRunConfig(
            task_name="detector",
            model_name="2d_cnn_tcn",
            data_root=data_root,
            output_root=output_root,
            allowed_labels=_parse_labels(labels),
            label_mode="detection",
            target_frames=target_frames,
            batch_size=batch_size,
            epochs=epochs,
            learning_rate=learning_rate,
            min_learning_rate=min_learning_rate,
            weight_decay=weight_decay,
            val_ratio=val_ratio,
            early_stopping_patience=early_stopping_patience,
            early_stopping_min_delta=early_stopping_min_delta,
            seed=seed,
            normalize=normalize,
            device=device,
        )
    )


def handle_train_3d_cnn(
    data_root: Annotated[
        Path,
        typer.Option(help="Root directory scanned recursively for canonical rd.npz samples."),
    ] = DEFAULT_DATA_ROOT,
    output_root: Annotated[
        Path,
        typer.Option(help="Directory where checkpoints and metrics are written."),
    ] = DEFAULT_OUTPUT_ROOT,
    labels: Annotated[
        str,
        typer.Option(help="Comma-separated gesture labels used for classification."),
    ] = DEFAULT_CLASSIFIER_LABELS,
    epochs: Annotated[int, typer.Option(help="Number of training epochs.")] = 20,
    batch_size: Annotated[int, typer.Option(help="Mini-batch size.")] = 8,
    learning_rate: Annotated[float, typer.Option(help="Adam learning rate.")] = 1e-3,
    min_learning_rate: Annotated[
        float,
        typer.Option(help="Minimum learning rate for cosine annealing."),
    ] = 1e-6,
    weight_decay: Annotated[float, typer.Option(help="Adam weight decay.")] = 1e-4,
    early_stopping_patience: Annotated[
        int,
        typer.Option(help="Stop when val accuracy does not improve for N epochs."),
    ] = 5,
    early_stopping_min_delta: Annotated[
        float,
        typer.Option(help="Minimum val accuracy improvement to reset patience."),
    ] = 1e-4,
    target_frames: Annotated[
        int,
        typer.Option(help="Fixed frame count after temporal resampling."),
    ] = 50,
    val_ratio: Annotated[
        float,
        typer.Option(help="Validation split ratio, stratified by label."),
    ] = 0.2,
    seed: Annotated[int, typer.Option(help="Random seed used for split and training.")] = 7,
    normalize: Annotated[
        bool,
        typer.Option(
            "--normalize/--no-normalize",
            help="Apply per-sample z-score normalization before training.",
        ),
    ] = True,
    device: Annotated[
        str | None,
        typer.Option(help="Explicit torch device such as cpu, cuda, or mps."),
    ] = None,
) -> None:
    """Train the compact `3D CNN` RD gesture classifier."""
    _run_training_command(
        config=TrainingRunConfig(
            task_name="classifier",
            model_name="3d_cnn",
            data_root=data_root,
            output_root=output_root,
            allowed_labels=_parse_labels(labels),
            label_mode="gesture",
            target_frames=target_frames,
            batch_size=batch_size,
            epochs=epochs,
            learning_rate=learning_rate,
            min_learning_rate=min_learning_rate,
            weight_decay=weight_decay,
            val_ratio=val_ratio,
            early_stopping_patience=early_stopping_patience,
            early_stopping_min_delta=early_stopping_min_delta,
            seed=seed,
            normalize=normalize,
            device=device,
        )
    )


def _run_training_command(*, config: TrainingRunConfig) -> None:
    """Run one training command and render a concise console summary."""
    try:
        from vassago.training.rd.runner import train_classifier

        result = train_classifier(config)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    best_epoch = max(result.history, key=lambda item: item.val_accuracy)
    console.print("RD training summary")
    console.print(f"task_name: {config.task_name}")
    console.print(f"model_name: {config.model_name}")
    console.print(f"run_dir: {result.run_dir}")
    console.print(f"labels: {', '.join(result.labels)}")
    console.print(f"epochs: {len(result.history)}")
    console.print(f"best_val_accuracy: {best_epoch.val_accuracy:.4f}")
    console.print(f"best_checkpoint: {result.best_checkpoint_path}")
    console.print(f"metrics: {result.metrics_path}")


def _parse_labels(labels: str) -> tuple[str, ...]:
    """Parse one comma-separated label list."""
    parsed = tuple(label.strip() for label in labels.split(",") if label.strip())
    if not parsed:
        msg = "At least one non-empty label must be provided."
        raise ValueError(msg)
    return parsed
