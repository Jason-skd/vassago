"""Tests for the point-cloud visualizer packet consumer."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING
from typing import cast

from vassago.collection.rd.visualizer import PointCloudVisualizerSession
from vassago.firmware.mmwave.point_cloud import POINT_CLOUD_TLV_TYPE
from vassago.firmware.mmwave.point_cloud import PointCloudFrame
from vassago.firmware.mmwave.protocol import HEADER_SIZE
from vassago.firmware.mmwave.protocol import MAGIC_WORD
from vassago.firmware.mmwave.protocol import TLV_HEADER_SIZE
from vassago.firmware.mmwave.protocol import MmwavePacketParser

if TYPE_CHECKING:
    from multiprocessing import Queue


class FakeQueue:
    """Minimal queue stub that records frames passed to put_nowait()."""

    def __init__(self) -> None:
        self.items: list[object] = []

    def put_nowait(self, item: object) -> None:
        """Record one queued item."""
        self.items.append(item)


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
        123,
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


def test_visualizer_session_consumes_decoded_point_cloud_packets() -> None:
    parser = MmwavePacketParser()
    packets = tuple(
        parser.feed(
            build_packet(
                7,
                [
                    (
                        POINT_CLOUD_TLV_TYPE,
                        build_point_cloud_payload((1.0, 2.0, 3.0, 4.0)),
                    )
                ],
            )
        )
    )
    fake_queue = FakeQueue()
    session = PointCloudVisualizerSession(frame_queue=cast("Queue", fake_queue))

    session.consume_packets(packets)

    assert len(fake_queue.items) == 1
    frame = cast("PointCloudFrame", fake_queue.items[0])
    assert frame.frame_number == 7
    assert frame.point_count == 1


def test_visualizer_session_skips_invalid_point_cloud_payloads() -> None:
    parser = MmwavePacketParser()
    packets = tuple(
        parser.feed(build_packet(4, [(POINT_CLOUD_TLV_TYPE, b"\x00\x01\x02")]))
    )
    fake_queue = FakeQueue()
    session = PointCloudVisualizerSession(frame_queue=cast("Queue", fake_queue))

    session.consume_packets(packets)

    assert fake_queue.items == []
