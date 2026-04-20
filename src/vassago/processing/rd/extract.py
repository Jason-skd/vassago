"""Strict raw_uart.bin to RD cube extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from vassago.processing.mmwave.config import load_mmwave_processing_config
from vassago.processing.mmwave.tlv import RANGE_DOPPLER_HEATMAP_TLV_TYPE
from vassago.processing.mmwave.tlv import decode_range_doppler_heatmap
from vassago.processing.mmwave.uart_packets import UartPacket
from vassago.processing.mmwave.uart_packets import slice_uart_packet_stream
from vassago.processing.rd.model import ExtractedRdCapture

if TYPE_CHECKING:
    from pathlib import Path


class RdExtractionError(ValueError):
    """Raised when a strict RD capture cannot be extracted."""


def extract_rd_capture(
    *,
    input_path: Path,
    config_path: Path,
) -> ExtractedRdCapture:
    """Extract an RD cube from one raw UART capture using one mmWave cfg."""
    processing_config = load_mmwave_processing_config(config_path)
    resolved_input_path = input_path.expanduser().resolve()
    if not resolved_input_path.is_file():
        msg = f"Input capture file not found: {resolved_input_path}"
        raise FileNotFoundError(msg)

    slice_result = slice_uart_packet_stream(resolved_input_path.read_bytes())
    if not slice_result.packets:
        msg = f"No complete packets were extracted from {resolved_input_path}"
        raise RdExtractionError(msg)

    rd_heatmaps = [
        _extract_packet_rd(
            packet=packet,
            range_bin_count=processing_config.range_bin_count,
            doppler_bin_count=processing_config.doppler_bin_count,
        )
        for packet in slice_result.packets
    ]

    return ExtractedRdCapture(
        source_path=resolved_input_path,
        config=processing_config,
        rd_cube_u16=np.asarray(rd_heatmaps, dtype=np.uint16),
    )


def _extract_packet_rd(
    *,
    packet: UartPacket,
    range_bin_count: int,
    doppler_bin_count: int,
) -> tuple[tuple[int, ...], ...]:
    """Extract the RD heatmap from one strict packet."""
    for tlv in packet.tlvs:
        if tlv.tlv_type != RANGE_DOPPLER_HEATMAP_TLV_TYPE:
            continue
        return decode_range_doppler_heatmap(
            tlv,
            range_bin_count=range_bin_count,
            doppler_bin_count=doppler_bin_count,
        ).heatmap_u16

    msg = f"Packet {packet.packet_index} does not contain RD TLV type 5"
    raise RdExtractionError(msg)
