"""Tests for the minimal mmWave smoke test parser."""

from __future__ import annotations

import struct

from vassago.mmwave_smoke_test import HEADER_SIZE
from vassago.mmwave_smoke_test import MAGIC_WORD
from vassago.mmwave_smoke_test import MmwavePacket
from vassago.mmwave_smoke_test import MmwavePacketParser
from vassago.mmwave_smoke_test import _read_cli_until_prompt
from vassago.mmwave_smoke_test import summarize_packets


def build_packet(frame_number: int, tlv_types: list[int]) -> bytes:
    """Build a minimal synthetic mmWave packet for parser tests."""
    tlv_payload = b""
    for tlv_type in tlv_types:
        payload = b"\x00\x01\x02\x03"
        tlv_payload += struct.pack("<II", tlv_type, 8 + len(payload)) + payload

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


def test_parser_extracts_packets_across_multiple_reads() -> None:
    """The parser should reconstruct a packet even when reads split it."""
    packet = build_packet(frame_number=42, tlv_types=[1, 7])
    parser = MmwavePacketParser()

    first_half = packet[:10]
    second_half = packet[10:]

    assert parser.feed(first_half) == []

    packets = parser.feed(second_half)

    assert len(packets) == 1
    assert packets[0].frame_number == 42
    assert packets[0].tlv_types == (1, 7)


def test_parser_resynchronizes_after_noise() -> None:
    """Noise before the magic word should be skipped cleanly."""
    packet = build_packet(frame_number=5, tlv_types=[3])
    parser = MmwavePacketParser()

    packets = parser.feed(b"noise-bytes" + packet)

    assert len(packets) == 1
    assert packets[0].frame_number == 5
    assert parser.invalid_packet_count == 0


def test_summarize_packets_counts_frame_gaps() -> None:
    """Frame gaps and TLV counts should be aggregated correctly."""
    packets = [
        MmwavePacket(1, 48, 0, 10, 0, 0, 1, 0, (1,)),
        MmwavePacket(1, 48, 0, 12, 0, 0, 2, 0, (1, 9)),
        MmwavePacket(1, 48, 0, 12, 0, 0, 1, 0, (9,)),
    ]

    summary = summarize_packets(
        packets=packets,
        bytes_read=1024,
        invalid_packet_count=2,
    )

    assert summary.bytes_read == 1024
    assert summary.valid_packet_count == 3
    assert summary.invalid_packet_count == 2
    assert summary.first_frame_number == 10
    assert summary.last_frame_number == 12
    assert summary.frame_gap_count == 1
    assert summary.non_monotonic_frame_count == 1
    assert summary.tlv_type_counts == {1: 2, 9: 2}


class FakeSerial:
    """Minimal serial stub for prompt fragmentation tests."""

    def __init__(self, chunks: list[bytes]) -> None:
        """Store the chunks that will be returned by read_all."""
        self._chunks = chunks

    def read_all(self) -> bytes:
        """Return the next chunk, or no bytes when exhausted."""
        return self._chunks.pop(0) if self._chunks else b""


def test_read_cli_until_prompt_handles_fragmented_prompt() -> None:
    """The CLI prompt may arrive split across multiple serial reads."""
    connection = FakeSerial([b"sensorStop\r\nDone\r\nmmw", b"Demo:/>\r\n"])

    lines = _read_cli_until_prompt(connection)  # type: ignore[arg-type]

    assert lines == ["sensorStop", "Done", "mmwDemo:/>"]
