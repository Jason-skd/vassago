"""Forward-shape tests for RD training baselines."""

from __future__ import annotations

import torch

from vassago.training.rd.models import Rd2dCnnTcnClassifier
from vassago.training.rd.models import Rd3dCnnClassifier


def test_rd_2d_cnn_tcn_classifier_emits_class_logits() -> None:
    model = Rd2dCnnTcnClassifier(num_classes=3)
    batch = torch.randn(2, 50, 128, 16)

    logits = model(batch)

    assert logits.shape == (2, 3)


def test_rd_3d_cnn_classifier_emits_class_logits() -> None:
    model = Rd3dCnnClassifier(num_classes=3)
    batch = torch.randn(2, 50, 128, 16)

    logits = model(batch)

    assert logits.shape == (2, 3)

