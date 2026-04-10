"""Known cfg metadata used by the bring-up CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class KnownMmwaveConfig:
    """One repository-managed cfg with user-facing metadata."""

    config_id: str
    path: Path
    label: str
    purpose: str
    risk: str
    recommended_for_bringup: bool


def repo_root() -> Path:
    """Return the repository root from inside the package tree."""
    return Path(__file__).resolve().parents[4]


def list_known_configs() -> list[KnownMmwaveConfig]:
    """Return the curated cfg list exposed by the bring-up CLI."""
    configs_root = repo_root() / "configs"
    return [
        KnownMmwaveConfig(
            config_id="baseline_pointcloud",
            path=configs_root / "profile_3d.cfg",
            label="Baseline Point Cloud",
            purpose="Conservative baseline for board + firmware bring-up.",
            risk="low",
            recommended_for_bringup=True,
        ),
        KnownMmwaveConfig(
            config_id="rd_candidate",
            path=configs_root / "rd_phase1_uart.cfg",
            label="RD Candidate",
            purpose="RD-over-UART candidate for later capture workflows.",
            risk="high",
            recommended_for_bringup=False,
        ),
    ]


def get_known_config(config_id: str) -> KnownMmwaveConfig:
    """Resolve a config id to a curated cfg entry."""
    for config in list_known_configs():
        if config.config_id == config_id:
            return config

    msg = f"Unknown cfg id: {config_id}"
    raise KeyError(msg)
