"""Training loop and artifact writing for RD detector/classifier baselines."""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import json
from pathlib import Path
import random

import numpy as np
from rich.console import Console
from rich.progress import BarColumn
from rich.progress import Progress
from rich.progress import TaskProgressColumn
from rich.progress import TextColumn
from rich.progress import TimeElapsedColumn

from typing import TYPE_CHECKING
from vassago.training.rd.config import TrainingRunConfig
from vassago.training.rd.dataset import TrainingSample
from vassago.training.rd.dataset import discover_training_samples
from vassago.training.rd.dataset import load_rd_tensor
from vassago.training.rd.dataset import split_dataset

console = Console()


@dataclass(slots=True, frozen=True)
class EpochMetrics:
    """Metrics recorded for one completed epoch."""

    epoch: int
    train_loss: float
    train_accuracy: float
    val_loss: float
    val_accuracy: float


@dataclass(slots=True, frozen=True)
class TrainingRunResult:
    """Summary returned after one detector/classifier training run."""

    run_dir: Path
    best_checkpoint_path: Path
    label_to_index_path: Path
    metrics_path: Path
    history: tuple[EpochMetrics, ...]
    labels: tuple[str, ...]


def train_classifier(config: TrainingRunConfig) -> TrainingRunResult:
    """Train one RD detector/classifier end-to-end and persist its artifacts."""
    torch = _import_torch()
    _seed_everything(seed=config.seed, torch=torch)

    scan_result = discover_training_samples(
        data_root=config.data_root,
        allowed_labels=config.allowed_labels,
        label_mode=config.label_mode,
    )
    split = split_dataset(
        samples=scan_result.samples,
        val_ratio=config.val_ratio,
        seed=config.seed,
    )
    label_to_index = {label: index for index, label in enumerate(scan_result.labels)}
    console.print("Preparing training run")
    console.print(f"  task_name: {config.task_name}")
    console.print(f"  model_name: {config.model_name}")
    console.print(f"  labels: {', '.join(scan_result.labels)}")
    console.print(f"  train_samples: {len(split.train_samples)}")
    console.print(f"  val_samples: {len(split.val_samples)}")

    model_module = _import_training_models()
    model = model_module.build_model(
        model_name=config.model_name,
        num_classes=len(scan_result.labels),
    )
    device = _resolve_device(device=config.device, torch=torch)
    model.to(device)

    train_dataset = _RdTorchDataset(
        samples=split.train_samples,
        label_to_index=label_to_index,
        target_frames=config.target_frames,
        normalize=config.normalize,
        torch=torch,
    )
    val_dataset = _RdTorchDataset(
        samples=split.val_samples,
        label_to_index=label_to_index,
        target_frames=config.target_frames,
        normalize=config.normalize,
        torch=torch,
    )
    train_loader = torch.utils.data.DataLoader(
        train_dataset,
        batch_size=config.batch_size,
        shuffle=True,
    )
    val_loader = torch.utils.data.DataLoader(
        val_dataset,
        batch_size=config.batch_size,
        shuffle=False,
    )

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=config.epochs,
        eta_min=config.min_learning_rate,
    )
    criterion = torch.nn.CrossEntropyLoss()

    run_dir = _create_run_dir(
        output_root=config.output_root,
        task_name=config.task_name,
        model_name=config.model_name,
    )
    metrics_path = run_dir / "metrics.json"
    checkpoint_path = run_dir / "best.pt"
    label_to_index_path = run_dir / "label_to_index.json"

    history: list[EpochMetrics] = []
    best_val_accuracy = float("-inf")
    best_epoch = 0
    no_improve_epochs = 0
    stopped_early = False
    for epoch in range(1, config.epochs + 1):
        console.print(f"Epoch {epoch}/{config.epochs}")
        train_loss, train_accuracy = _run_epoch(
            model=model,
            data_loader=train_loader,
            optimizer=optimizer,
            criterion=criterion,
            device=device,
            torch=torch,
            training=True,
            epoch=epoch,
            total_epochs=config.epochs,
        )
        val_loss, val_accuracy = _run_epoch(
            model=model,
            data_loader=val_loader,
            optimizer=None,
            criterion=criterion,
            device=device,
            torch=torch,
            training=False,
            epoch=epoch,
            total_epochs=config.epochs,
        )
        epoch_metrics = EpochMetrics(
            epoch=epoch,
            train_loss=train_loss,
            train_accuracy=train_accuracy,
            val_loss=val_loss,
            val_accuracy=val_accuracy,
        )
        history.append(epoch_metrics)
        if val_accuracy > best_val_accuracy + config.early_stopping_min_delta:
            best_val_accuracy = val_accuracy
            best_epoch = epoch
            no_improve_epochs = 0
            torch.save(
                {
                    "model_name": config.model_name,
                    "model_state_dict": model.state_dict(),
                    "labels": scan_result.labels,
                    "target_frames": config.target_frames,
                    "normalize": config.normalize,
                    "best_epoch": best_epoch,
                    "best_val_accuracy": best_val_accuracy,
                },
                checkpoint_path,
            )
            console.print(
                "  new_best_checkpoint: "
                f"val_accuracy={val_accuracy:.4f} -> {checkpoint_path}"
            )
        else:
            no_improve_epochs += 1

        scheduler.step()
        current_lr = float(optimizer.param_groups[0]["lr"])
        console.print(
            "  summary: "
            f"train_loss={train_loss:.4f} "
            f"train_acc={train_accuracy:.4f} "
            f"val_loss={val_loss:.4f} "
            f"val_acc={val_accuracy:.4f} "
            f"lr={current_lr:.8f}"
        )
        if (
            config.early_stopping_patience > 0
            and no_improve_epochs >= config.early_stopping_patience
        ):
            stopped_early = True
            console.print(
                "  early_stopping: "
                f"no improvement for {no_improve_epochs} epochs "
                f"(best_epoch={best_epoch}, best_val_acc={best_val_accuracy:.4f})"
            )
            break

    label_to_index_path.write_text(
        json.dumps(label_to_index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metrics_payload = {
        "run_config": _serialize_run_config(config=config),
        "labels": list(scan_result.labels),
        "train_sample_count": len(split.train_samples),
        "val_sample_count": len(split.val_samples),
        "best_epoch": best_epoch,
        "best_val_accuracy": best_val_accuracy,
        "stopped_early": stopped_early,
        "epochs_completed": len(history),
        "history": [asdict(epoch_metrics) for epoch_metrics in history],
    }
    metrics_path.write_text(
        json.dumps(metrics_payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    return TrainingRunResult(
        run_dir=run_dir,
        best_checkpoint_path=checkpoint_path,
        label_to_index_path=label_to_index_path,
        metrics_path=metrics_path,
        history=tuple(history),
        labels=scan_result.labels,
    )


if TYPE_CHECKING:
    from torch.utils.data import Dataset as _TorchDataset
else:
    _TorchDataset = object  # type: ignore[assignment]


class _RdTorchDataset(_TorchDataset):
    """A torch dataset that lazily loads canonical `rd.npz` samples."""

    def __init__(
        self,
        *,
        samples: tuple[TrainingSample, ...],
        label_to_index: dict[str, int],
        target_frames: int,
        normalize: bool,
        torch,
    ) -> None:
        self._samples = samples
        self._label_to_index = label_to_index
        self._target_frames = target_frames
        self._normalize = normalize
        self._torch = torch

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> tuple["np.ndarray", "np.ndarray"]:
        sample = self._samples[index]
        rd_tensor = load_rd_tensor(
            npz_path=sample.path,
            target_frames=self._target_frames,
            normalize=self._normalize,
        )
        label_index = self._label_to_index[sample.label]
        features = self._torch.from_numpy(rd_tensor.astype(np.float32, copy=False))
        target = self._torch.tensor(label_index, dtype=self._torch.int64)
        return features, target


def _run_epoch(
    *,
    model,
    data_loader,
    optimizer,
    criterion,
    device,
    torch,
    training: bool,
    epoch: int,
    total_epochs: int,
) -> tuple[float, float]:
    """Run one train or validation epoch and return loss/accuracy."""
    if training:
        model.train()
    else:
        model.eval()

    total_loss = 0.0
    total_examples = 0
    total_correct = 0
    stage_name = "train" if training else "val"
    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("loss={task.fields[loss]:.4f}"),
        TextColumn("acc={task.fields[acc]:.4f}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
    with progress:
        task_id = progress.add_task(
            f"{stage_name} epoch {epoch}/{total_epochs}",
            total=len(data_loader),
            loss=0.0,
            acc=0.0,
        )
        for batch_features, batch_targets in data_loader:
            batch_features = batch_features.to(device)
            batch_targets = batch_targets.to(device)

            if training and optimizer is not None:
                optimizer.zero_grad()

            with torch.set_grad_enabled(training):
                logits = model(batch_features)
                loss = criterion(logits, batch_targets)
                if training and optimizer is not None:
                    loss.backward()
                    optimizer.step()

            batch_size = int(batch_targets.shape[0])
            total_loss += float(loss.item()) * batch_size
            total_examples += batch_size
            predictions = torch.argmax(logits, dim=1)
            total_correct += int((predictions == batch_targets).sum().item())
            progress.update(
                task_id,
                advance=1,
                loss=total_loss / total_examples,
                acc=total_correct / total_examples,
            )

    mean_loss = total_loss / total_examples
    accuracy = total_correct / total_examples
    return mean_loss, accuracy


def _create_run_dir(*, output_root: Path, task_name: str, model_name: str) -> Path:
    """Create one timestamped run directory."""
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root.expanduser().resolve() / task_name / model_name / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _seed_everything(*, seed: int, torch) -> None:
    """Seed Python, NumPy, and torch RNGs for reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _resolve_device(*, device: str | None, torch):
    """Resolve the actual torch device used for training."""
    if device is not None:
        return torch.device(device)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _serialize_run_config(*, config: TrainingRunConfig) -> dict[str, object]:
    """Convert one run config to a JSON-friendly mapping."""
    return {
        "model_name": config.model_name,
        "task_name": config.task_name,
        "data_root": str(config.data_root.expanduser().resolve()),
        "output_root": str(config.output_root.expanduser().resolve()),
        "allowed_labels": list(config.allowed_labels),
        "label_mode": config.label_mode,
        "target_frames": config.target_frames,
        "batch_size": config.batch_size,
        "epochs": config.epochs,
        "learning_rate": config.learning_rate,
        "min_learning_rate": config.min_learning_rate,
        "weight_decay": config.weight_decay,
        "val_ratio": config.val_ratio,
        "early_stopping_patience": config.early_stopping_patience,
        "early_stopping_min_delta": config.early_stopping_min_delta,
        "seed": config.seed,
        "normalize": config.normalize,
        "device": config.device,
    }


def _import_torch():
    """Import torch lazily and raise a targeted guidance message when missing."""
    try:
        import torch
    except ModuleNotFoundError as exc:
        msg = (
            "PyTorch is required for training commands. "
            "Install the training dependency group first, for example: "
            "`uv sync --group train`."
        )
        raise RuntimeError(msg) from exc
    return torch


def _import_training_models():
    """Import training models lazily so the main CLI can load without torch."""
    from vassago.training.rd import models

    return models
