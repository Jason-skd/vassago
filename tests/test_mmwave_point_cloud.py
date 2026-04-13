"""Tests for reusable point-cloud decoding helpers."""

from __future__ import annotations

import struct

import pytest

from vassago.firmware.mmwave.point_cloud import POINT_CLOUD_TLV_TYPE
from vassago.firmware.mmwave.point_cloud import PointCloudStreamDecoder
from vassago.firmware.mmwave.point_cloud import decode_point_cloud_tlv
from vassago.firmware.mmwave.point_cloud import extract_point_cloud_frame
from vassago.firmware.mmwave.point_cloud import iter_point_cloud_frames
from vassago.firmware.mmwave.protocol import HEADER_SIZE
from vassago.firmware.mmwave.protocol import MAGIC_WORD
from vassago.firmware.mmwave.protocol import TLV_HEADER_SIZE
from vassago.firmware.mmwave.protocol import MmwavePacketParser


def build_packet(
    frame_number: int,
    tlvs: list[tuple[int, bytes]],
    *,
    length_mode: str = "payload",
) -> bytes:
    """Build one synthetic packet with the requested TLVs."""
    tlv_payload = b""
    for tlv_type, payload in tlvs:
        tlv_length = (
            len(payload) if length_mode == "payload" else TLV_HEADER_SIZE + len(payload)
        )
        tlv_payload += struct.pack("<II", tlv_type, tlv_length) + payload

    total_packet_length = HEADER_SIZE + len(tlv_payload)
    header = MAGIC_WORD + struct.pack(
        "<8I",
        0x03060000,
        total_packet_length,
        0xA6843,
        frame_number,
        321,
        0,
        len(tlvs),
        0,
    )
    return header + tlv_payload


def build_point_cloud_payload(*points: tuple[float, float, float, float]) -> bytes:
    """Pack one or more semantic points into a synthetic TLV payload."""
    payload = bytearray()
    for point in points:
        payload.extend(struct.pack("<4f", *point))
    return bytes(payload)


def test_extract_point_cloud_frame_decodes_one_packet() -> None:
    parser = MmwavePacketParser()
    packets = parser.feed(
        build_packet(
            7,
            [
                (
                    POINT_CLOUD_TLV_TYPE,
                    build_point_cloud_payload(
                        (1.0, 2.0, 3.0, 4.0),
                        (-1.5, 0.5, 9.0, -0.25),
                    ),
                )
            ],
        )
    )

    frame = extract_point_cloud_frame(packets[0])

    assert frame is not None
    assert frame.frame_number == 7
    assert frame.time_cpu_cycles == 321
    assert frame.point_count == 2
    assert frame.points[0].x == 1.0
    assert frame.points[1].velocity == -0.25


def test_iter_point_cloud_frames_skips_packets_without_point_cloud() -> None:
    parser = MmwavePacketParser()
    packets = parser.feed(
        build_packet(1, [(5, b"\x00\x01")])
        + build_packet(
            2,
            [(POINT_CLOUD_TLV_TYPE, build_point_cloud_payload((0.0, 1.0, 2.0, 3.0)))],
        )
    )

    frames = iter_point_cloud_frames(packets)

    assert len(frames) == 1
    assert frames[0].frame_number == 2
    assert frames[0].point_count == 1


def test_point_cloud_stream_decoder_handles_chunked_streams() -> None:
    decoder = PointCloudStreamDecoder()
    packet = build_packet(
        9,
        [
            (
                POINT_CLOUD_TLV_TYPE,
                build_point_cloud_payload((0.1, 0.2, 0.3, 0.4)),
            )
        ],
        length_mode="total",
    )

    frames = decoder.feed(packet[:11])
    frames.extend(decoder.feed(packet[11:]))

    assert len(frames) == 1
    assert frames[0].frame_number == 9
    assert frames[0].point_count == 1
    assert decoder.invalid_packet_count == 0


def test_decode_point_cloud_tlv_rejects_non_multiple_payload_size() -> None:
    parser = MmwavePacketParser()
    packets = parser.feed(build_packet(4, [(POINT_CLOUD_TLV_TYPE, b"\x00\x01\x02")]))

    with pytest.raises(ValueError, match="multiple"):
        decode_point_cloud_tlv(packets[0].tlvs[0])
