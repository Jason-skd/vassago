"""Tests for canonical raw_uart.bin to rd.npz extraction workflows."""

from __future__ import annotations

import json
import random
import struct
from typing import TYPE_CHECKING

import numpy as np

from vassago.collection.rd import session as collection_session
from vassago.firmware.mmwave.config import KnownMmwaveConfig
from vassago.firmware.mmwave.protocol import HEADER_SIZE
from vassago.firmware.mmwave.protocol import MAGIC_WORD
from vassago.processing.rd.artifact import extract_manifest_samples
from vassago.processing.rd.artifact import write_rd_npz
from vassago.processing.rd.extract import extract_rd_capture
from vassago.processing.rd.model import BackgroundRdNpzSample
from vassago.processing.rd.model import RdNpzSample

if TYPE_CHECKING:
    from pathlib import Path


def write_test_config(config_path: Path, *, frame_periodicity_ms: int = 100) -> Path:
    """Write a minimal cfg fixture with 8x4 RD shape."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        (
            "channelCfg 15 7 0\n"
            "profileCfg 0 60 7 3 24 0 0 166 1 8 12500 0 0 158\n"
            f"frameCfg 0 2 4 0 {frame_periodicity_ms} 1 0\n"
        ),
        encoding="utf-8",
    )
    return config_path


def build_rd_packet(
    *,
    frame_number: int,
    range_bin_count: int,
    doppler_bin_count: int,
) -> bytes:
    """Build one synthetic RD packet matching the strict decoder."""
    value_count = range_bin_count * doppler_bin_count
    rd_payload = struct.pack(
        f"<{value_count}H",
        *range(value_count),
    )
    tlv_payload = struct.pack("<II", 5, len(rd_payload)) + rd_payload
    padding = b"\x00" * 12
    total_packet_length = HEADER_SIZE + len(tlv_payload) + len(padding)
    header = MAGIC_WORD + struct.pack(
        "<8I",
        0x03060000,
        total_packet_length,
        0xA6843,
        frame_number,
        0,
        0,
        1,
        0,
    )
    return header + tlv_payload + padding


def test_extract_rd_capture_decodes_rd_cube(tmp_path) -> None:
    config_path = write_test_config(tmp_path / "rd.cfg")
    raw_uart_path = tmp_path / "sample" / "raw_uart.bin"
    raw_uart_path.parent.mkdir(parents=True, exist_ok=True)
    raw_uart_path.write_bytes(
        b"".join(
            [
                build_rd_packet(
                    frame_number=10,
                    range_bin_count=8,
                    doppler_bin_count=4,
                ),
                build_rd_packet(
                    frame_number=11,
                    range_bin_count=8,
                    doppler_bin_count=4,
                ),
            ],
        ),
    )

    capture = extract_rd_capture(
        input_path=raw_uart_path,
        config_path=config_path,
    )

    assert capture.frame_count == 2
    assert capture.rd_cube_u16.shape == (2, 8, 4)
    assert capture.rd_cube_u16.dtype == np.uint16
    assert capture.rd_cube_u16[0, 0, 0] == 0
    assert capture.rd_cube_u16[0, 7, 3] == 31


def test_write_rd_npz_persists_canonical_arrays(tmp_path) -> None:
    output_path = tmp_path / "sample" / "rd.npz"
    sample = RdNpzSample(
        rd_u16=np.arange(32, dtype=np.uint16).reshape(1, 8, 4),
        capture_window_s=(0.0, 5.0),
        target_window_s=(1.0, 2.0),
        marked_window_s=None,
        gesture="wave",
        subject_name="alice",
        hand="right",
        distance_m=0.5,
        angle_deg=None,
        environment="lab",
        radar_id="radar_01",
        firmware_id="fw_01",
        firmware_config_id="rd_candidate",
        session_id="session_01",
        take_id="take01",
    )

    written_path = write_rd_npz(sample=sample, output_path=output_path)

    assert written_path == output_path.resolve()
    with np.load(written_path, allow_pickle=False) as payload:
        assert payload["schema_version"].tolist() == "rd_npz_v1"
        assert payload["rd"].shape == (1, 8, 4)
        assert payload["capture_window_s"].tolist() == [0.0, 5.0]
        assert payload["target_window_s"].tolist() == [1.0, 2.0]
        assert np.isnan(payload["marked_window_s"]).all()
        assert payload["gesture"].tolist() == "wave"
        assert payload["subject_name"].tolist() == "alice"
        assert payload["hand"].tolist() == "right"
        assert payload["distance_m"].item() == np.float32(0.5)
        assert np.isnan(payload["angle_deg"]).item()
        assert payload["environment"].tolist() == "lab"
        assert payload["radar_id"].tolist() == "radar_01"
        assert payload["firmware_id"].tolist() == "fw_01"
        assert payload["firmware_config_id"].tolist() == "rd_candidate"
        assert payload["session_id"].tolist() == "session_01"
        assert payload["take_id"].tolist() == "take01"


def test_write_rd_npz_persists_background_arrays(tmp_path) -> None:
    output_path = tmp_path / "sample" / "rd_background.npz"
    sample = BackgroundRdNpzSample(
        rd_u16=np.arange(32, dtype=np.uint16).reshape(1, 8, 4),
        capture_window_s=(10.0, 15.0),
        collection_type=collection_session.COLLECTION_TYPE_WHITE_SPACE,
        subject_name="alice",
        hand="right",
        distance_m=0.5,
        angle_deg=None,
        environment="lab",
        radar_id="radar_01",
        firmware_id="fw_01",
        firmware_config_id="rd_candidate",
        session_id="session_01",
        segment_id="segment0001",
    )

    written_path = write_rd_npz(sample=sample, output_path=output_path)

    assert written_path == output_path.resolve()
    with np.load(written_path, allow_pickle=False) as payload:
        assert payload["schema_version"].tolist() == "rd_background_npz_v1"
        assert payload["rd"].shape == (1, 8, 4)
        assert payload["capture_window_s"].tolist() == [10.0, 15.0]
        assert payload["collection_type"].tolist() == "white_space"
        assert payload["subject_name"].tolist() == "alice"
        assert payload["segment_id"].tolist() == "segment0001"


def test_extract_manifest_samples_writes_rd_npz_for_each_accepted_take(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = write_test_config(tmp_path / "configs" / "rd.cfg")
    session_dir = tmp_path / "sessions" / "session_01"
    take_one_dir = session_dir / "takes" / "take01"
    take_two_dir = session_dir / "takes" / "take02"
    take_one_dir.mkdir(parents=True, exist_ok=True)
    take_two_dir.mkdir(parents=True, exist_ok=True)
    (take_one_dir / "raw_uart.bin").write_bytes(
        build_rd_packet(frame_number=20, range_bin_count=8, doppler_bin_count=4),
    )
    (take_two_dir / "raw_uart.bin").write_bytes(
        build_rd_packet(frame_number=21, range_bin_count=8, doppler_bin_count=4),
    )
    manifest_path = session_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "collection_type": collection_session.COLLECTION_TYPE_GESTURE,
                "session_id": "session_01",
                "subject_name": "alice",
                "hand": "right",
                "distance_m": 0.5,
                "angle_deg": 0.0,
                "environment": "lab",
                "radar_id": "radar_01",
                "firmware_id": "fw_01",
                "firmware_config_id": "rd_candidate",
                "gesture": "wave",
                "takes": [
                    {
                        "take_id": "take01",
                        "status": "accepted",
                        "raw_uart_path": str((take_one_dir / "raw_uart.bin").resolve()),
                        "capture_window": {"start_s": 0.0, "end_s": 5.0},
                        "target_window": {"start_s": 1.0, "end_s": 2.0},
                        "marked_window": {"start_s": 1.1, "end_s": 2.1},
                    },
                    {
                        "take_id": "take02",
                        "status": "accepted",
                        "raw_uart_path": str((take_two_dir / "raw_uart.bin").resolve()),
                        "capture_window": {"start_s": 0.0, "end_s": 5.0},
                        "target_window": {"start_s": 1.5, "end_s": 2.5},
                        "marked_window": None,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "vassago.processing.rd.artifact.mmwave_config.get_known_config",
        lambda _config_id: KnownMmwaveConfig(
            config_id="rd_candidate",
            path=config_path,
            label="RD",
            purpose="test",
            risk="high",
            recommended_for_bringup=False,
        ),
    )

    outputs = extract_manifest_samples(manifest_path=manifest_path)

    assert len(outputs) == 2
    assert all(output.name == "rd.npz" for output in outputs)
    assert all(output.is_file() for output in outputs)
    with np.load(outputs[0], allow_pickle=False) as payload:
        assert payload["rd"].shape == (1, 8, 4)
        assert payload["gesture"].tolist() == "wave"
        assert payload["session_id"].tolist() == "session_01"
        assert payload["take_id"].tolist() == "take01"


def test_extract_manifest_samples_writes_background_rd_npz_and_index(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = write_test_config(
        tmp_path / "configs" / "rd_background.cfg",
        frame_periodicity_ms=1000,
    )
    session_dir = tmp_path / "sessions" / "session_background"
    background_dir = session_dir / "background"
    background_dir.mkdir(parents=True, exist_ok=True)
    raw_uart_path = background_dir / collection_session.BACKGROUND_RAW_UART_FILENAME
    raw_uart_path.write_bytes(
        b"".join(
            build_rd_packet(
                frame_number=frame_number,
                range_bin_count=8,
                doppler_bin_count=4,
            )
            for frame_number in range(1, 16)
        )
    )
    manifest_path = session_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "collection_type": collection_session.COLLECTION_TYPE_WHITE_SPACE,
                "session_id": "session_background",
                "subject_name": "alice",
                "hand": "right",
                "distance_m": 0.5,
                "angle_deg": 0.0,
                "environment": "lab",
                "radar_id": "radar_01",
                "firmware_id": "fw_01",
                "firmware_config_id": "rd_candidate",
                "background_plan": {
                    "window_duration_s": 5.0,
                    "target_segment_count": 2,
                    "selection_seed": 7,
                    "selection_policy": "random_after_capture",
                    "save_policy": "keep_full_capture",
                },
                "background_capture": {
                    "status": "completed",
                    "raw_uart_path": str(raw_uart_path.resolve()),
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "vassago.processing.rd.artifact.mmwave_config.get_known_config",
        lambda _config_id: KnownMmwaveConfig(
            config_id="rd_candidate",
            path=config_path,
            label="RD",
            purpose="test",
            risk="high",
            recommended_for_bringup=False,
        ),
    )

    outputs = extract_manifest_samples(manifest_path=manifest_path)

    assert len(outputs) == 2
    assert all(output.is_file() for output in outputs)
    assert all(output.name == "rd.npz" for output in outputs)

    index_path = background_dir / "rd_segments_manifest.json"
    assert index_path.is_file()
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    expected_window_indices = sorted(
        random.Random(7).sample(range(3), 2)  # noqa: S311 - test mirrors deterministic slicing.
    )

    assert index_payload["schema_version"] == "rd_background_segment_index_v1"
    assert index_payload["session_id"] == "session_background"
    assert index_payload["collection_type"] == "white_space"
    assert index_payload["window_duration_s"] == 5.0
    assert index_payload["target_segment_count"] == 2
    assert index_payload["selection_seed"] == 7
    assert index_payload["frame_period_s"] == 1.0
    assert index_payload["frames_per_window"] == 5
    assert index_payload["total_frame_count"] == 15
    assert index_payload["candidate_window_count"] == 3
    assert [segment["window_index"] for segment in index_payload["segments"]] == (
        expected_window_indices
    )

    with np.load(outputs[0], allow_pickle=False) as payload:
        assert payload["schema_version"].tolist() == "rd_background_npz_v1"
        assert payload["rd"].shape == (5, 8, 4)
        assert payload["collection_type"].tolist() == "white_space"
        assert payload["segment_id"].tolist() == "segment0001"
        assert payload["capture_window_s"].tolist() == [
            expected_window_indices[0] * 5.0,
            (expected_window_indices[0] + 1) * 5.0,
        ]
