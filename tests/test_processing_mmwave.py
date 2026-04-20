"""Tests for strict offline mmWave packet and RD config decoding."""

from __future__ import annotations

import struct

import pytest

from vassago.firmware.mmwave.protocol import HEADER_SIZE
from vassago.firmware.mmwave.protocol import MAGIC_WORD
from vassago.processing.mmwave.config import load_mmwave_processing_config
from vassago.processing.mmwave.tlv import TlvDecodeError
from vassago.processing.mmwave.tlv import decode_range_doppler_heatmap
from vassago.processing.mmwave.uart_packets import decode_uart_packet
from vassago.processing.mmwave.uart_packets import slice_uart_packet_stream


def build_uart_packet(
    *,
    frame_number: int,
    tlvs: list[tuple[int, bytes]],
    padding_bytes: bytes = b"",
) -> bytes:
    """Build one synthetic packet using payload-length TLV headers."""
    tlv_payload = b"".join(
        struct.pack("<II", tlv_type, len(payload)) + payload
        for tlv_type, payload in tlvs
    )
    total_packet_length = HEADER_SIZE + len(tlv_payload) + len(padding_bytes)
    header = MAGIC_WORD + struct.pack(
        "<8I",
        0x03060000,
        total_packet_length,
        0xA6843,
        frame_number,
        0,
        0,
        len(tlvs),
        0,
    )
    return header + tlv_payload + padding_bytes


def test_load_mmwave_processing_config_derives_rd_shape(tmp_path) -> None:
    config_path = tmp_path / "rd.cfg"
    config_path.write_text(
        (
            "channelCfg 15 7 0\n"
            "profileCfg 0 60 7 3 24 0 0 166 1 8 12500 0 0 158\n"
            "frameCfg 0 2 4 0 100 1 0\n"
        ),
        encoding="utf-8",
    )

    config = load_mmwave_processing_config(config_path)

    assert config.range_bin_count == 8
    assert config.doppler_bin_count == 4
    assert config.tx_antenna_count == 3
    assert config.chirps_per_frame == 12
    assert config.frame_period_s == 0.1


def test_slice_uart_packet_stream_and_decode_rd_heatmap() -> None:
    rd_payload = struct.pack("<8H", 0, 1, 2, 3, 4, 5, 6, 7)
    packet_bytes = build_uart_packet(
        frame_number=30,
        tlvs=[(5, rd_payload)],
        padding_bytes=b"\x00" * 12,
    )

    result = slice_uart_packet_stream(b"noise" + packet_bytes)
    packet = decode_uart_packet(
        packet_bytes=result.packets[0].raw_packet,
        packet_index=0,
        packet_start_offset=result.packets[0].packet_start_offset,
    )
    decoded = decode_range_doppler_heatmap(
        packet.tlvs[0],
        range_bin_count=4,
        doppler_bin_count=2,
    )

    assert len(result.packets) == 1
    assert result.leading_discarded_bytes == 5
    assert result.packets[0].padding_size == 12
    assert decoded.shape == (4, 2)
    assert decoded.heatmap_u16 == ((0, 1), (2, 3), (4, 5), (6, 7))


def test_decode_range_doppler_heatmap_rejects_shape_mismatch() -> None:
    packet_bytes = build_uart_packet(
        frame_number=40,
        tlvs=[(5, struct.pack("<8H", 0, 1, 2, 3, 4, 5, 6, 7))],
    )
    packet = decode_uart_packet(
        packet_bytes=packet_bytes,
        packet_index=0,
        packet_start_offset=0,
    )

    with pytest.raises(TlvDecodeError):
        decode_range_doppler_heatmap(
            packet.tlvs[0],
            range_bin_count=2,
            doppler_bin_count=2,
        )
