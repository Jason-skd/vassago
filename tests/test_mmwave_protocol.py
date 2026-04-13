"""Tests for protocol-level mmWave packet parsing."""

from __future__ import annotations

import struct

from vassago.firmware.mmwave.protocol import HEADER_SIZE
from vassago.firmware.mmwave.protocol import MAGIC_WORD
from vassago.firmware.mmwave.protocol import TLV_HEADER_SIZE
from vassago.firmware.mmwave.protocol import MmwavePacketParser
from vassago.firmware.mmwave.protocol import summarize_packets


def build_packet(
    frame_number: int,
    tlvs: list[tuple[int, bytes]],
    *,
    length_mode: str = "payload",
    num_detected_objects: int = 0,
    trailing_padding: bytes = b"",
) -> bytes:
    """Build a minimal synthetic mmWave packet."""
    tlv_payload = b""
    for tlv_type, payload in tlvs:
        tlv_length = (
            len(payload) if length_mode == "payload" else TLV_HEADER_SIZE + len(payload)
        )
        tlv_payload += struct.pack("<II", tlv_type, tlv_length) + payload

    total_packet_length = HEADER_SIZE + len(tlv_payload) + len(trailing_padding)
    header = MAGIC_WORD + struct.pack(
        "<8I",
        0x03060000,
        total_packet_length,
        0xA6843,
        frame_number,
        0,
        num_detected_objects,
        len(tlvs),
        0,
    )
    return header + tlv_payload + trailing_padding


def test_packet_parser_recovers_after_leading_noise() -> None:
    parser = MmwavePacketParser()

    packets = parser.feed(
        b"noise"
        + build_packet(
            10,
            [
                (1, b"\x00\x01\x02\x03"),
                (5, b"\x04\x05\x06\x07"),
                (6, b"\x08\x09\x0a\x0b"),
            ],
        )
    )

    assert len(packets) == 1
    assert packets[0].frame_number == 10
    assert packets[0].tlv_types == (1, 5, 6)
    assert packets[0].tlvs[1].payload == b"\x04\x05\x06\x07"
    assert packets[0].tlvs[1].length_mode == "payload"


def test_packet_parser_reads_tlv_payloads_with_total_length_mode() -> None:
    parser = MmwavePacketParser()

    packets = parser.feed(
        build_packet(
            10,
            [
                (1, b"\x00\x01\x02\x03"),
                (5, b"\x10\x11\x12\x13\x14\x15"),
            ],
            length_mode="total",
        )
    )

    assert len(packets) == 1
    assert packets[0].tlv_types == (1, 5)
    assert packets[0].tlvs[0].payload == b"\x00\x01\x02\x03"
    assert packets[0].tlvs[0].length_mode == "total"
    assert packets[0].tlvs[1].payload == b"\x10\x11\x12\x13\x14\x15"


def test_packet_parser_prefers_plausible_payload_path_for_ambiguous_packet() -> None:
    parser = MmwavePacketParser()
    point_payload = struct.pack("<4f", 1.0, 0.25, -0.01, 0.0)
    packets = parser.feed(
        build_packet(
            7,
            [
                (1, point_payload),
                (7, b"\x36\x00\xba\x01"),
                (5, b"X" * 24),
                (6, b"Y" * 16 + struct.pack("<II", 1, 49)),
                (9, b"Z" * 28),
            ],
            num_detected_objects=1,
            trailing_padding=b"\x00" * 8,
        )
    )

    assert len(packets) == 1
    assert packets[0].tlv_types == (1, 7, 5, 6, 9)
    assert tuple(tlv.length_mode for tlv in packets[0].tlvs) == (
        "payload",
        "payload",
        "payload",
        "payload",
        "payload",
    )
    assert packets[0].tlvs[0].payload == point_payload


def test_summarize_packets_counts_frame_gaps_and_tlv_types() -> None:
    parser = MmwavePacketParser()
    packets = parser.feed(
        build_packet(10, [(1, b"\x00"), (5, b"\x01")])
        + build_packet(13, [(5, b"\x02"), (6, b"\x03")])
    )

    summary = summarize_packets(
        packets=packets,
        bytes_read=1234,
        invalid_packet_count=0,
    )

    assert summary.bytes_read == 1234
    assert summary.valid_packet_count == 2
    assert summary.frame_gap_count == 2
    assert summary.tlv_type_counts == {1: 1, 5: 2, 6: 1}
