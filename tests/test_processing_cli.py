"""CLI tests for RD processing commands."""

from __future__ import annotations

import json
import struct

from typer.testing import CliRunner

from vassago.cli import app
from vassago.collection.rd import session as collection_session
from vassago.firmware.mmwave.config import KnownMmwaveConfig
from vassago.firmware.mmwave.protocol import HEADER_SIZE
from vassago.firmware.mmwave.protocol import MAGIC_WORD

runner = CliRunner()


def write_test_config(config_path, *, frame_periodicity_ms: int = 100) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        (
            "channelCfg 15 7 0\n"
            "profileCfg 0 60 7 3 24 0 0 166 1 8 12500 0 0 158\n"
            f"frameCfg 0 2 4 0 {frame_periodicity_ms} 1 0\n"
        ),
        encoding="utf-8",
    )


def build_rd_packet(*, frame_number: int) -> bytes:
    value_count = 8 * 4
    rd_payload = struct.pack(f"<{value_count}H", *range(value_count))
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


def test_processing_rd_extract_command_writes_artifact(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "configs" / "rd.cfg"
    write_test_config(config_path)
    session_dir = tmp_path / "sessions" / "session_01"
    take_dir = session_dir / "takes" / "take01"
    take_dir.mkdir(parents=True, exist_ok=True)
    raw_uart_path = take_dir / "raw_uart.bin"
    raw_uart_path.write_bytes(build_rd_packet(frame_number=20))
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
                        "raw_uart_path": str(raw_uart_path.resolve()),
                        "capture_window": {"start_s": 0.0, "end_s": 5.0},
                        "target_window": {"start_s": 1.0, "end_s": 2.0},
                        "marked_window": {"start_s": 1.1, "end_s": 2.1},
                    }
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

    result = runner.invoke(
        app,
        [
            "processing",
            "rd",
            "extract",
            "--manifest",
            str(manifest_path),
        ],
    )

    assert result.exit_code == 0
    assert "written_artifacts: 1" in result.output
    assert (take_dir / "rd.npz").is_file()


def test_processing_rd_extract_all_command_writes_artifacts(
    tmp_path, monkeypatch
) -> None:
    config_path = tmp_path / "configs" / "rd.cfg"
    write_test_config(config_path)

    sessions_root = tmp_path / "sessions"

    session_one_dir = sessions_root / "session_01"
    take_one_dir = session_one_dir / "takes" / "take01"
    take_one_dir.mkdir(parents=True, exist_ok=True)
    raw_uart_one_path = take_one_dir / "raw_uart.bin"
    raw_uart_one_path.write_bytes(build_rd_packet(frame_number=20))
    manifest_one_path = session_one_dir / "manifest.json"
    manifest_one_path.write_text(
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
                        "raw_uart_path": str(raw_uart_one_path.resolve()),
                        "capture_window": {"start_s": 0.0, "end_s": 5.0},
                        "target_window": {"start_s": 1.0, "end_s": 2.0},
                        "marked_window": {"start_s": 1.1, "end_s": 2.1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    session_two_dir = sessions_root / "session_02"
    take_two_dir = session_two_dir / "takes" / "take01"
    take_two_dir.mkdir(parents=True, exist_ok=True)
    raw_uart_two_path = take_two_dir / "raw_uart.bin"
    raw_uart_two_path.write_bytes(build_rd_packet(frame_number=21))
    manifest_two_path = session_two_dir / "manifest.json"
    manifest_two_path.write_text(
        json.dumps(
            {
                "collection_type": collection_session.COLLECTION_TYPE_GESTURE,
                "session_id": "session_02",
                "subject_name": "bob",
                "hand": "left",
                "distance_m": None,
                "angle_deg": None,
                "environment": "lab",
                "radar_id": "radar_01",
                "firmware_id": "fw_01",
                "firmware_config_id": "rd_candidate",
                "gesture": "wave",
                "takes": [
                    {
                        "take_id": "take01",
                        "status": "accepted",
                        "raw_uart_path": str(raw_uart_two_path.resolve()),
                        "capture_window": {"start_s": 0.0, "end_s": 5.0},
                        "target_window": {"start_s": 1.0, "end_s": 2.0},
                        "marked_window": None,
                    }
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

    result = runner.invoke(
        app,
        [
            "processing",
            "rd",
            "extract-all",
            "--sessions-root",
            str(sessions_root),
        ],
    )

    assert result.exit_code == 0
    assert "RD Extract All Summary" in result.output
    assert "checked_manifests: 2" in result.output
    assert "written_artifacts: 2" in result.output
    assert (take_one_dir / "rd.npz").is_file()
    assert (take_two_dir / "rd.npz").is_file()


def test_processing_rd_extract_command_writes_background_artifacts(
    tmp_path, monkeypatch
) -> None:
    config_path = tmp_path / "configs" / "rd_background.cfg"
    write_test_config(config_path, frame_periodicity_ms=1000)
    session_dir = tmp_path / "sessions" / "session_background"
    background_dir = session_dir / "background"
    background_dir.mkdir(parents=True, exist_ok=True)
    raw_uart_path = background_dir / collection_session.BACKGROUND_RAW_UART_FILENAME
    raw_uart_path.write_bytes(
        b"".join(
            build_rd_packet(frame_number=frame_number) for frame_number in range(1, 16)
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

    result = runner.invoke(
        app,
        [
            "processing",
            "rd",
            "extract",
            "--manifest",
            str(manifest_path),
        ],
    )

    assert result.exit_code == 0
    assert "written_artifacts: 2" in result.output
    assert (background_dir / "rd_segments_manifest.json").is_file()
    assert (background_dir / "segments" / "segment0001" / "rd.npz").is_file()
    assert (background_dir / "segments" / "segment0002" / "rd.npz").is_file()
