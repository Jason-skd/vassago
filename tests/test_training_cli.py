"""CLI tests for RD training commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from typer.testing import CliRunner

from vassago.cli import app

runner = CliRunner()


@dataclass(slots=True, frozen=True)
class _EpochMetrics:
    epoch: int
    train_loss: float
    train_accuracy: float
    val_loss: float
    val_accuracy: float


@dataclass(slots=True, frozen=True)
class _TrainingRunResult:
    run_dir: Path
    best_checkpoint_path: Path
    label_to_index_path: Path
    metrics_path: Path
    history: tuple[_EpochMetrics, ...]
    labels: tuple[str, ...]


def test_training_rd_command_routes_to_2d_cnn_tcn_runner(monkeypatch, tmp_path) -> None:
    def fake_train_classifier(config):
        assert config.task_name == "detector"
        assert config.model_name == "2d_cnn_tcn"
        return _TrainingRunResult(
            run_dir=tmp_path / "run",
            best_checkpoint_path=tmp_path / "run" / "best.pt",
            label_to_index_path=tmp_path / "run" / "label_to_index.json",
            metrics_path=tmp_path / "run" / "metrics.json",
            history=(
                _EpochMetrics(
                    epoch=1,
                    train_loss=1.0,
                    train_accuracy=0.8,
                    val_loss=0.9,
                    val_accuracy=0.75,
                ),
            ),
            labels=("gesture", "non_gesture"),
        )

    monkeypatch.setattr(
        "vassago.training.rd.runner.train_classifier",
        fake_train_classifier,
    )

    result = runner.invoke(app, ["training", "rd", "train-2d-cnn-tcn"])

    assert result.exit_code == 0
    assert "RD training summary" in result.output
    assert "detector" in result.output
    assert "2d_cnn_tcn" in result.output


def test_training_rd_command_routes_to_3d_cnn_classifier_runner(
    monkeypatch, tmp_path
) -> None:
    def fake_train_classifier(config):
        assert config.task_name == "classifier"
        assert config.model_name == "3d_cnn"
        return _TrainingRunResult(
            run_dir=tmp_path / "run",
            best_checkpoint_path=tmp_path / "run" / "best.pt",
            label_to_index_path=tmp_path / "run" / "label_to_index.json",
            metrics_path=tmp_path / "run" / "metrics.json",
            history=(
                _EpochMetrics(
                    epoch=1,
                    train_loss=1.0,
                    train_accuracy=0.8,
                    val_loss=0.9,
                    val_accuracy=0.75,
                ),
            ),
            labels=("wave", "flip", "circle_cw"),
        )

    monkeypatch.setattr(
        "vassago.training.rd.runner.train_classifier",
        fake_train_classifier,
    )

    result = runner.invoke(app, ["training", "rd", "train-3d-cnn"])

    assert result.exit_code == 0
    assert "classifier" in result.output
    assert "3d_cnn" in result.output


def test_training_rd_command_routes_to_2d_classifier_runner(
    monkeypatch, tmp_path
) -> None:
    def fake_train_classifier(config):
        assert config.task_name == "classifier"
        assert config.model_name == "2d_cnn_tcn"
        return _TrainingRunResult(
            run_dir=tmp_path / "run",
            best_checkpoint_path=tmp_path / "run" / "best.pt",
            label_to_index_path=tmp_path / "run" / "label_to_index.json",
            metrics_path=tmp_path / "run" / "metrics.json",
            history=(
                _EpochMetrics(
                    epoch=1,
                    train_loss=1.0,
                    train_accuracy=0.8,
                    val_loss=0.9,
                    val_accuracy=0.75,
                ),
            ),
            labels=("wave", "flip", "circle_cw"),
        )

    monkeypatch.setattr(
        "vassago.training.rd.runner.train_classifier",
        fake_train_classifier,
    )

    result = runner.invoke(app, ["training", "rd", "train-2d-cnn-tcn-classifier"])

    assert result.exit_code == 0
    assert "classifier" in result.output
    assert "2d_cnn_tcn" in result.output


def test_training_rd_command_routes_to_3d_detector_runner(
    monkeypatch, tmp_path
) -> None:
    def fake_train_classifier(config):
        assert config.task_name == "detector"
        assert config.model_name == "3d_cnn"
        return _TrainingRunResult(
            run_dir=tmp_path / "run",
            best_checkpoint_path=tmp_path / "run" / "best.pt",
            label_to_index_path=tmp_path / "run" / "label_to_index.json",
            metrics_path=tmp_path / "run" / "metrics.json",
            history=(
                _EpochMetrics(
                    epoch=1,
                    train_loss=1.0,
                    train_accuracy=0.8,
                    val_loss=0.9,
                    val_accuracy=0.75,
                ),
            ),
            labels=("gesture", "non_gesture"),
        )

    monkeypatch.setattr(
        "vassago.training.rd.runner.train_classifier",
        fake_train_classifier,
    )

    result = runner.invoke(app, ["training", "rd", "train-3d-cnn-detector"])

    assert result.exit_code == 0
    assert "detector" in result.output
    assert "3d_cnn" in result.output
