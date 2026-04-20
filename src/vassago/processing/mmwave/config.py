"""Minimal cfg parsing helpers for offline RD extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vassago.firmware.mmwave.cfg import CfgCommand
from vassago.firmware.mmwave.cfg import load_cfg_commands

if TYPE_CHECKING:
    from pathlib import Path

PROFILE_CFG_NUM_ADC_SAMPLES_ARG_INDEX = 9
FRAME_CFG_CHIRP_START_ARG_INDEX = 0
FRAME_CFG_CHIRP_END_ARG_INDEX = 1
FRAME_CFG_LOOP_COUNT_ARG_INDEX = 2
FRAME_CFG_PERIODICITY_ARG_INDEX = 4
CHANNEL_CFG_RX_MASK_ARG_INDEX = 0
CHANNEL_CFG_TX_MASK_ARG_INDEX = 1
MIN_PROFILE_CFG_ARGS = 10
MIN_FRAME_CFG_ARGS = 5
MIN_CHANNEL_CFG_ARGS = 2


@dataclass(slots=True, frozen=True)
class MmwaveProcessingConfig:
    """Derived processing dimensions and timing from one mmWave cfg file."""

    source_path: Path
    rx_antenna_count: int
    tx_antenna_count: int
    num_adc_samples: int
    range_bin_count: int
    chirp_start_index: int
    chirp_end_index: int
    loops_per_frame: int
    chirps_per_frame: int
    doppler_bin_count: int
    frame_period_s: float


def load_mmwave_processing_config(config_path: Path) -> MmwaveProcessingConfig:
    """Parse one cfg file into the dimensions needed for RD extraction."""
    resolved_path = config_path.expanduser().resolve()
    if not resolved_path.is_file():
        msg = f"Config file not found: {resolved_path}"
        raise FileNotFoundError(msg)

    channel_args, profile_args, frame_args = _read_required_command_args(resolved_path)
    return _build_processing_config(
        resolved_path=resolved_path,
        channel_args=channel_args,
        profile_args=profile_args,
        frame_args=frame_args,
    )


def _read_required_command_args(
    resolved_path: Path,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Read the cfg command arguments required for RD dimension inference."""
    channel_command: CfgCommand | None = None
    profile_command: CfgCommand | None = None
    frame_command: CfgCommand | None = None

    for command in load_cfg_commands(resolved_path):
        if command.name == "channelCfg":
            _require_min_args(command, minimum=MIN_CHANNEL_CFG_ARGS)
            channel_command = command
        elif command.name == "profileCfg":
            _require_min_args(command, minimum=MIN_PROFILE_CFG_ARGS)
            profile_command = command
        elif command.name == "frameCfg":
            _require_min_args(command, minimum=MIN_FRAME_CFG_ARGS)
            frame_command = command

    if channel_command is None:
        msg = f"channelCfg not found in {resolved_path}"
        raise ValueError(msg)
    if profile_command is None:
        msg = f"profileCfg not found in {resolved_path}"
        raise ValueError(msg)
    if frame_command is None:
        msg = f"frameCfg not found in {resolved_path}"
        raise ValueError(msg)

    return channel_command.args, profile_command.args, frame_command.args


def _build_processing_config(
    *,
    resolved_path: Path,
    channel_args: tuple[str, ...],
    profile_args: tuple[str, ...],
    frame_args: tuple[str, ...],
) -> MmwaveProcessingConfig:
    """Build the typed processing config from required cfg command arguments."""
    rx_antenna_count = _count_enabled_channels(
        int(channel_args[CHANNEL_CFG_RX_MASK_ARG_INDEX], 0),
    )
    tx_antenna_count = _count_enabled_channels(
        int(channel_args[CHANNEL_CFG_TX_MASK_ARG_INDEX], 0),
    )
    if rx_antenna_count <= 0:
        msg = f"channelCfg enables no RX antennas in {resolved_path}"
        raise ValueError(msg)
    if tx_antenna_count <= 0:
        msg = f"channelCfg enables no TX antennas in {resolved_path}"
        raise ValueError(msg)

    num_adc_samples = int(profile_args[PROFILE_CFG_NUM_ADC_SAMPLES_ARG_INDEX], 0)
    if num_adc_samples <= 0:
        msg = f"profileCfg numAdcSamples must be positive in {resolved_path}"
        raise ValueError(msg)

    chirp_start_index = int(frame_args[FRAME_CFG_CHIRP_START_ARG_INDEX], 0)
    chirp_end_index = int(frame_args[FRAME_CFG_CHIRP_END_ARG_INDEX], 0)
    loops_per_frame = int(frame_args[FRAME_CFG_LOOP_COUNT_ARG_INDEX], 0)
    if chirp_end_index < chirp_start_index:
        msg = f"frameCfg chirp indices are invalid in {resolved_path}"
        raise ValueError(msg)
    if loops_per_frame <= 0:
        msg = f"frameCfg loop count must be positive in {resolved_path}"
        raise ValueError(msg)

    chirps_per_frame = (chirp_end_index - chirp_start_index + 1) * loops_per_frame
    if chirps_per_frame % tx_antenna_count != 0:
        msg = (
            "frameCfg chirp count is not divisible by enabled TX antennas in "
            f"{resolved_path}"
        )
        raise ValueError(msg)

    range_bin_count = _next_power_of_two(num_adc_samples)
    doppler_bin_count = chirps_per_frame // tx_antenna_count
    frame_period_s = float(frame_args[FRAME_CFG_PERIODICITY_ARG_INDEX]) / 1000.0

    return MmwaveProcessingConfig(
        source_path=resolved_path,
        rx_antenna_count=rx_antenna_count,
        tx_antenna_count=tx_antenna_count,
        num_adc_samples=num_adc_samples,
        range_bin_count=range_bin_count,
        chirp_start_index=chirp_start_index,
        chirp_end_index=chirp_end_index,
        loops_per_frame=loops_per_frame,
        chirps_per_frame=chirps_per_frame,
        doppler_bin_count=doppler_bin_count,
        frame_period_s=frame_period_s,
    )


def _require_min_args(command: CfgCommand, *, minimum: int) -> None:
    """Reject incomplete cfg commands required for RD dimension inference."""
    if len(command.args) < minimum:
        msg = f"{command.name} line is incomplete: {command.text}"
        raise ValueError(msg)


def _count_enabled_channels(mask: int) -> int:
    """Return the number of enabled channels in a bitmask."""
    return mask.bit_count()


def _next_power_of_two(value: int) -> int:
    """Round a positive integer up to the next power of two."""
    if value <= 0:
        msg = "value must be positive"
        raise ValueError(msg)
    return 1 << (value - 1).bit_length()
