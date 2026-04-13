"""Tests for capture orchestration helpers."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING
from typing import cast

from vassago.collection.rd import capture as collection_capture
from vassago.collection.rd import quick_qc as collection_quick_qc
from vassago.collection.rd.config import WindowRange
from vassago.firmware.mmwave.protocol import HEADER_SIZE
from vassago.firmware.mmwave.protocol import MAGIC_WORD
from vassago.firmware.mmwave.protocol import TLV_HEADER_SIZE

if TYPE_CHECKING:
    import serial


def build_packet(
    frame_number: int,
    tlvs: list[tuple[int, bytes]],
    *,
    length_mode: str = "payload",
) -> bytes:
    """Build one synthetic packet for capture-level tests."""
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
        0,
        0,
        len(tlvs),
        0,
    )
    return header + tlv_payload


def test_review_capture_take_streams_summary_into_qc(monkeypatch) -> None:
    raw_capture = build_packet(3, [(1, b"\x00\x01\x02\x03")])
    streamed_chunks = (raw_capture[:9], raw_capture[9:])

    def fake_capture_take(_connection, **kwargs):
        packet_parser = kwargs["packet_parser"]
        packet_consumers = tuple(kwargs.get("packet_consumers", ()))
        for chunk in streamed_chunks:
            packets = tuple(packet_parser.feed(chunk))
            for consumer in packet_consumers:
                consumer(packets)
        attempt_plan = kwargs["attempt_plan"]
        return collection_capture.TakeCaptureResult(
            raw_capture=raw_capture,
            capture_window=attempt_plan.capture_window,
            target_window=attempt_plan.target_window,
            marked_window=WindowRange(1.0, 2.2),
        )

    observed: dict[str, object] = {}

    def fake_evaluate_capture(**kwargs):
        observed["summary"] = kwargs["summary"]
        return collection_quick_qc.QuickQcDecision(
            accepted=True,
            reasons=(),
        )

    monkeypatch.setattr(
        "vassago.collection.rd.capture.capture_take",
        fake_capture_take,
    )
    monkeypatch.setattr(
        "vassago.collection.rd.capture.quick_qc.evaluate_capture",
        fake_evaluate_capture,
    )

    attempt_plan = collection_capture.AttemptPlan(
        countdown_duration_s=5.0,
        capture_window=WindowRange(0.0, 5.0),
        target_window=WindowRange(1.0, 2.0),
        marked_window_deadline_s=2.25,
        capture_start_delay_s=4.0,
        end_mark_key="space",
    )

    reviewed_capture = collection_capture.review_capture_take(
        cast("serial.Serial", object()),
        attempt_plan=attempt_plan,
        read_size=1024,
    )

    assert reviewed_capture.summary.bytes_read == len(raw_capture)
    assert reviewed_capture.summary.valid_packet_count == 1
    assert reviewed_capture.summary.tlv_type_counts == {1: 1}
    assert observed["summary"] == reviewed_capture.summary
    assert reviewed_capture.qc_decision.accepted is True


def test_summarize_raw_capture_matches_packet_summary_contract() -> None:
    raw_capture = build_packet(1, [(1, b"\x00")]) + build_packet(4, [(5, b"\x01")])

    summary = collection_capture.summarize_raw_capture(raw_capture)

    assert summary.bytes_read == len(raw_capture)
    assert summary.valid_packet_count == 2
    assert summary.frame_gap_count == 2
    assert summary.tlv_type_counts == {1: 1, 5: 1}


def test_review_capture_take_forwards_packets_to_visualizer_when_enabled(
    monkeypatch,
) -> None:
    raw_capture = build_packet(5, [(1, b"\x00\x01\x02\x03")])
    observed: dict[str, object] = {
        "enabled": None,
        "frame_numbers": [],
        "closed": False,
    }

    def fake_capture_take(_connection, **kwargs):
        packet_parser = kwargs["packet_parser"]
        packet_consumers = tuple(kwargs.get("packet_consumers", ()))
        packets = tuple(packet_parser.feed(raw_capture))
        for consumer in packet_consumers:
            consumer(packets)
        attempt_plan = kwargs["attempt_plan"]
        return collection_capture.TakeCaptureResult(
            raw_capture=raw_capture,
            capture_window=attempt_plan.capture_window,
            target_window=attempt_plan.target_window,
            marked_window=WindowRange(1.0, 2.0),
        )

    class FakeVisualizerSession:
        def consume_packets(self, packets) -> None:
            observed["frame_numbers"] = [packet.frame_number for packet in packets]

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr(
        "vassago.collection.rd.capture.capture_take",
        fake_capture_take,
    )
    monkeypatch.setattr(
        "vassago.collection.rd.capture.quick_qc.evaluate_capture",
        lambda **_kwargs: collection_quick_qc.QuickQcDecision(
            accepted=True,
            reasons=(),
        ),
    )
    monkeypatch.setattr(
        "vassago.collection.rd.capture.visualizer.start_visualizer",
        lambda *, enabled: (
            observed.__setitem__("enabled", enabled) or FakeVisualizerSession()
        ),
    )

    attempt_plan = collection_capture.AttemptPlan(
        countdown_duration_s=5.0,
        capture_window=WindowRange(0.0, 5.0),
        target_window=WindowRange(1.0, 2.0),
        marked_window_deadline_s=2.25,
        capture_start_delay_s=4.0,
        end_mark_key="space",
    )

    reviewed_capture = collection_capture.review_capture_take(
        cast("serial.Serial", object()),
        attempt_plan=attempt_plan,
        read_size=1024,
        enable_visualizer=True,
    )

    assert observed["enabled"] is True
    assert observed["frame_numbers"] == [5]
    assert observed["closed"] is True
    assert reviewed_capture.summary.valid_packet_count == 1
