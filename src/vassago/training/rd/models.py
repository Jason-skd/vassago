"""PyTorch baselines for RD gesture classification."""

from __future__ import annotations

import torch
from torch import nn

from vassago.training.rd.config import ModelName


class FrameEncoder2d(nn.Module):
    """A small 2D CNN used to encode one RD frame into one feature vector."""

    def __init__(self, *, feature_dim: int) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(),
            nn.MaxPool2d(kernel_size=2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(kernel_size=2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d(output_size=(1, 1)),
            nn.Flatten(),
            nn.Linear(64, feature_dim),
            nn.ReLU(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Encode one batch of single-channel RD frames."""
        return self.network(x)


class TemporalBlock(nn.Module):
    """One residual 1D temporal-convolution block."""

    def __init__(self, *, channels: int, dilation: int) -> None:
        super().__init__()
        padding = dilation
        self.conv1 = nn.Conv1d(
            channels,
            channels,
            kernel_size=3,
            padding=padding,
            dilation=dilation,
        )
        self.bn1 = nn.BatchNorm1d(channels)
        self.conv2 = nn.Conv1d(
            channels,
            channels,
            kernel_size=3,
            padding=padding,
            dilation=dilation,
        )
        self.bn2 = nn.BatchNorm1d(channels)
        self.activation = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Apply one residual temporal block."""
        residual = x
        x = self.activation(self.bn1(self.conv1(x)))
        x = self.bn2(self.conv2(x))
        x = self.activation(x + residual)
        return x


class Rd2dCnnTcnClassifier(nn.Module):
    """A light classifier that encodes each frame then models temporal evolution."""

    def __init__(self, *, num_classes: int, feature_dim: int = 128) -> None:
        super().__init__()
        self.encoder = FrameEncoder2d(feature_dim=feature_dim)
        self.temporal = nn.Sequential(
            TemporalBlock(channels=feature_dim, dilation=1),
            TemporalBlock(channels=feature_dim, dilation=2),
            TemporalBlock(channels=feature_dim, dilation=4),
        )
        self.classifier = nn.Linear(feature_dim, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Classify one batch of RD clips shaped `(B, T, R, D)`."""
        batch_size, frame_count, range_bin_count, doppler_bin_count = x.shape
        frames = x.reshape(
            batch_size * frame_count, 1, range_bin_count, doppler_bin_count
        )
        encoded_frames = self.encoder(frames)
        encoded_frames = encoded_frames.reshape(batch_size, frame_count, -1)
        temporal_features = encoded_frames.transpose(1, 2)
        temporal_features = self.temporal(temporal_features)
        pooled_features = temporal_features.mean(dim=2)
        return self.classifier(pooled_features)


class Rd3dCnnClassifier(nn.Module):
    """A 3D spatial stem followed by a temporal head for RD clips."""

    def __init__(self, *, num_classes: int) -> None:
        super().__init__()
        # Keep temporal resolution in early layers; pool only over (R, D).
        self.spatial_stem = nn.Sequential(
            nn.Conv3d(1, 16, kernel_size=3, padding=1),
            nn.BatchNorm3d(16),
            nn.ReLU(),
            nn.MaxPool3d(kernel_size=(1, 2, 2)),
            nn.Conv3d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm3d(32),
            nn.ReLU(),
            nn.MaxPool3d(kernel_size=(1, 2, 2)),
            nn.Conv3d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm3d(64),
            nn.ReLU(),
            nn.MaxPool3d(kernel_size=(1, 2, 2)),
            nn.Conv3d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm3d(128),
            nn.ReLU(),
        )
        self.temporal_head = nn.Sequential(
            TemporalBlock(channels=128, dilation=1),
            TemporalBlock(channels=128, dilation=2),
            TemporalBlock(channels=128, dilation=4),
        )
        self.classifier = nn.Linear(128, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Classify one batch of RD clips shaped `(B, T, R, D)`."""
        x = x.unsqueeze(1)
        features = self.spatial_stem(x)
        features = features.mean(dim=(3, 4))
        features = self.temporal_head(features)
        pooled = features.mean(dim=2)
        return self.classifier(pooled)


def build_model(*, model_name: ModelName, num_classes: int) -> nn.Module:
    """Build one supported classifier architecture by name."""
    if model_name == "2d_cnn_tcn":
        return Rd2dCnnTcnClassifier(num_classes=num_classes)
    if model_name == "3d_cnn":
        return Rd3dCnnClassifier(num_classes=num_classes)

    msg = f"Unsupported model_name: {model_name!r}"
    raise ValueError(msg)
