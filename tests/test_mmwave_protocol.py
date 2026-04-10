"""Tests for protocol-level mmWave packet parsing."""

from __future__ import annotations

import struct

from vassago.firmware.mmwave.protocol import HEADER_SIZE
from vassago.firmware.mmwave.protocol import MAGIC_WORD
from vassago.firmware.mmwave.protocol import MmwavePacketParser
from vassago.firmware.mmwave.protocol import summarize_packets


def build_packet(
    frame_number: int,
    tlv_types: list[int],
) -> bytes:
    """Build a minimal synthetic mmWave packet."""
    tlv_payload = b""
    for tlv_type in tlv_types:
        payload = b"\x00\x01\x02\x03"
        tlv_payload += struct.pack("<II", tlv_type, len(payload)) + payload

    total_packet_length = HEADER_SIZE + len(tlv_payload)
    header = MAGIC_WORD + struct.pack(
        "<8I",
        0x03060000,
        total_packet_length,
        0xA6843,
        frame_number,
        0,
        0,
        len(tlv_types),
        0,
    )
    return header + tlv_payload


def test_packet_parser_recovers_after_leading_noise() -> None:
    parser = MmwavePacketParser()

    packets = parser.feed(b"noise" + build_packet(10, [1, 5, 6]))

    assert len(packets) == 1
    assert packets[0].frame_number == 10
    assert packets[0].tlv_types == (1, 5, 6)


def test_summarize_packets_counts_frame_gaps_and_tlv_types() -> None:
    parser = MmwavePacketParser()
    packets = parser.feed(build_packet(10, [1, 5]) + build_packet(13, [5, 6]))

    summary = summarize_packets(
        packets=packets,
        bytes_read=1234,
        invalid_packet_count=0,
    )

    assert summary.bytes_read == 1234
    assert summary.valid_packet_count == 2
    assert summary.frame_gap_count == 2
    assert summary.tlv_type_counts == {1: 1, 5: 2, 6: 1}
