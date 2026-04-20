"""CLI tests for RD processing commands."""

from __future__ import annotations

import json
import struct

from typer.testing import CliRunner

from vassago.cli import app
from vassago.firmware.mmwave.config import KnownMmwaveConfig
from vassago.firmware.mmwave.protocol import HEADER_SIZE
from vassago.firmware.mmwave.protocol import MAGIC_WORD

runner = CliRunner()


def write_test_config(config_path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        (
            "channelCfg 15 7 0\n"
            "profileCfg 0 60 7 3 24 0 0 166 1 8 12500 0 0 158\n"
            "frameCfg 0 2 4 0 100 1 0\n"
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
