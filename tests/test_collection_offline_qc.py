from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from vassago.cli import app
from vassago.collection.rd import metadata_qc
from vassago.collection.rd import offline_qc
from vassago.collection.rd import quick_qc
from vassago.collection.rd import session as collection_session
from vassago.collection.rd.qc_contract import QC_PLUGIN_OFFLINE
from vassago.collection.rd.qc_contract import QC_SEVERITY_ERROR
from vassago.collection.rd.qc_contract import QC_SEVERITY_WARN
from vassago.collection.rd.qc_contract import OfflineQcSessionContext
from vassago.firmware.mmwave.protocol import HEADER_SIZE
from vassago.firmware.mmwave.protocol import MAGIC_WORD

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def test_run_metadata_qc_accepts_valid_manifest_contract(tmp_path) -> None:
    manifest_path, manifest = _write_manifest(tmp_path)

    report = metadata_qc.run_metadata_qc(
        OfflineQcSessionContext(
            manifest_path=manifest_path,
            manifest=manifest,
        )
    )

    assert report.findings == ()
    assert report.has_errors is False


def test_run_metadata_qc_flags_missing_top_level_field_and_default_drift(
    tmp_path,
) -> None:
    manifest_path, manifest = _write_manifest(tmp_path)
    manifest.pop("gesture_options")
    manifest["hand"] = "left"

    report = metadata_qc.run_metadata_qc(
        OfflineQcSessionContext(
            manifest_path=manifest_path,
            manifest=manifest,
        )
    )

    assert report.has_errors is True
    assert tuple(
        finding.code for finding in report.findings_for(severity=QC_SEVERITY_ERROR)
    ) == (metadata_qc.CODE_MISSING_FIELD,)
    assert tuple(
        finding.field_path
        for finding in report.findings_for(severity=QC_SEVERITY_ERROR)
    ) == ("gesture_options",)
    assert tuple(
        finding.code for finding in report.findings_for(severity=QC_SEVERITY_WARN)
    ) == (metadata_qc.CODE_SNAPSHOT_MISMATCH,)
    assert tuple(
        finding.field_path for finding in report.findings_for(severity=QC_SEVERITY_WARN)
    ) == ("hand",)


def test_run_metadata_qc_warns_on_firmware_config_id_default_drift(tmp_path) -> None:
    manifest_path, manifest = _write_manifest(tmp_path)
    manifest["firmware_config_id"] = "other_mmwave_cfg"

    report = metadata_qc.run_metadata_qc(
        OfflineQcSessionContext(
            manifest_path=manifest_path,
            manifest=manifest,
        )
    )

    assert tuple(
        finding.code for finding in report.findings_for(severity=QC_SEVERITY_WARN)
    ) == (metadata_qc.CODE_SNAPSHOT_MISMATCH,)
    assert tuple(
        finding.field_path for finding in report.findings_for(severity=QC_SEVERITY_WARN)
    ) == ("firmware_config_id",)


def test_run_metadata_qc_accepts_valid_background_manifest_contract(
    tmp_path,
) -> None:
    manifest_path, manifest = _write_manifest(tmp_path)
    manifest["collection_type"] = collection_session.COLLECTION_TYPE_WHITE_SPACE
    manifest["background_plan"] = {
        "sample_ratio": 2.0,
        "default_recording_duration_multiplier": 1.25,
        "window_duration_s": 5.0,
        "target_segment_count": 2,
        "planned_recording_duration_s": 12.5,
        "selection_policy": "random_after_capture",
        "save_policy": "keep_full_capture",
        "selection_seed": 7,
    }
    manifest["background_capture"] = {
        "status": "planned",
        "raw_uart_path": None,
        "started_at": None,
        "completed_at": None,
        "interrupted_at": None,
        "recording_duration_s": None,
        "recorded_bytes": None,
    }
    manifest["takes"] = []

    report = metadata_qc.run_metadata_qc(
        OfflineQcSessionContext(
            manifest_path=manifest_path,
            manifest=manifest,
        )
    )

    assert report.findings == ()


def test_run_metadata_qc_accepts_legacy_manifest_after_loader_backfill(
    tmp_path,
) -> None:
    manifest_path, manifest = _write_manifest(tmp_path)
    manifest.pop("collection_type")
    manifest.pop("companion_profile_id")
    manifest.pop("background_plan")
    manifest.pop("background_capture")
    config_snapshot = manifest["config_snapshot"]
    assert isinstance(config_snapshot, dict)
    config_snapshot["config_id"] = "rd_phase1_default"
    config_snapshot.pop("default_companion_profile_id")
    collection_session.write_manifest(manifest_path=manifest_path, manifest=manifest)

    report = offline_qc.run_offline_qc(manifest_path=manifest_path)

    assert not [
        finding
        for finding in report.findings
        if finding.code == metadata_qc.CODE_MISSING_FIELD
    ]


def test_run_offline_qc_replays_quick_qc_for_valid_accepted_take(tmp_path) -> None:
    manifest_path, _manifest = _write_manifest(tmp_path)

    report = offline_qc.run_offline_qc(manifest_path=manifest_path)

    assert report.findings == ()
    assert report.has_errors is False


def test_run_offline_qc_surfaces_quick_qc_findings_per_take(tmp_path) -> None:
    manifest_path, _manifest = _write_manifest(
        tmp_path,
        raw_capture=b"",
        marked_window=None,
    )

    report = offline_qc.run_offline_qc(manifest_path=manifest_path)

    assert tuple(finding.plugin for finding in report.findings) == (
        "quick_qc",
        "quick_qc",
        "quick_qc",
    )
    assert tuple(finding.code for finding in report.findings) == (
        quick_qc.REASON_MISSING_END_MARK,
        quick_qc.REASON_EMPTY_CAPTURE,
        quick_qc.REASON_NO_VALID_PACKETS,
    )
    assert tuple(finding.take_id for finding in report.findings) == (
        "take01",
        "take01",
        "take01",
    )


def test_run_offline_qc_accepts_completed_background_capture(tmp_path) -> None:
    manifest_path, _manifest = _write_background_manifest(tmp_path)

    report = offline_qc.run_offline_qc(manifest_path=manifest_path)

    assert report.findings == ()
    assert report.has_errors is False


def test_run_offline_qc_requires_completed_background_capture(tmp_path) -> None:
    manifest_path, manifest = _write_background_manifest(tmp_path)
    background_capture = manifest["background_capture"]
    assert isinstance(background_capture, dict)
    background_capture["status"] = collection_session.BACKGROUND_CAPTURE_STATUS_PLANNED
    background_capture["raw_uart_path"] = None
    background_capture["completed_at"] = None
    background_capture["recording_duration_s"] = None
    background_capture["recorded_bytes"] = None
    collection_session.write_manifest(manifest_path=manifest_path, manifest=manifest)

    report = offline_qc.run_offline_qc(manifest_path=manifest_path)

    assert tuple(finding.plugin for finding in report.findings) == (QC_PLUGIN_OFFLINE,)
    assert tuple(finding.code for finding in report.findings) == (
        offline_qc.CODE_BACKGROUND_CAPTURE_NOT_COMPLETED,
    )
    assert tuple(finding.field_path for finding in report.findings) == (
        "background_capture.status",
    )


def test_run_offline_qc_surfaces_background_capture_size_mismatch(tmp_path) -> None:
    manifest_path, manifest = _write_background_manifest(
        tmp_path,
        raw_capture=b"abcdef",
        recorded_bytes=5,
    )
    collection_session.write_manifest(manifest_path=manifest_path, manifest=manifest)

    report = offline_qc.run_offline_qc(manifest_path=manifest_path)

    assert tuple(finding.plugin for finding in report.findings) == (QC_PLUGIN_OFFLINE,)
    assert tuple(finding.code for finding in report.findings) == (
        offline_qc.CODE_BACKGROUND_CAPTURE_SIZE_MISMATCH,
    )
    assert tuple(finding.field_path for finding in report.findings) == (
        "background_capture.recorded_bytes",
    )


def test_run_offline_qc_all_returns_empty_report_when_sessions_root_is_missing(
    tmp_path,
) -> None:
    run_result = offline_qc.run_offline_qc_all(sessions_root=tmp_path / "missing")

    assert run_result.checked_manifest_count == 0
    assert run_result.manifest_results == ()
    assert run_result.report.findings == ()
    assert run_result.report.has_errors is False


def test_run_offline_qc_all_merges_reports_across_manifests(tmp_path) -> None:
    _write_session_manifest(tmp_path, session_id="session_a")
    manifest_path, manifest = _write_session_manifest(tmp_path, session_id="session_b")
    manifest.pop("gesture_options")
    collection_session.write_manifest(manifest_path=manifest_path, manifest=manifest)

    run_result = offline_qc.run_offline_qc_all(sessions_root=tmp_path)

    assert run_result.checked_manifest_count == 2
    assert tuple(result.manifest_path for result in run_result.manifest_results) == (
        tmp_path / "session_a" / "manifest.json",
        tmp_path / "session_b" / "manifest.json",
    )
    assert tuple(
        result.report.has_errors for result in run_result.manifest_results
    ) == (
        False,
        True,
    )
    assert run_result.report.has_errors is True


def test_run_offline_qc_all_surfaces_manifest_load_errors(tmp_path) -> None:
    session_dir = tmp_path / "session_bad"
    session_dir.mkdir()
    manifest_path = session_dir / "manifest.json"
    manifest_path.write_text("[]\n", encoding="utf-8")

    run_result = offline_qc.run_offline_qc_all(sessions_root=tmp_path)

    assert run_result.checked_manifest_count == 1
    assert tuple(finding.plugin for finding in run_result.report.findings) == (
        QC_PLUGIN_OFFLINE,
    )
    assert tuple(finding.code for finding in run_result.report.findings) == (
        offline_qc.CODE_MANIFEST_LOAD_ERROR,
    )
    assert run_result.manifest_results[0].manifest_path == manifest_path


def test_collection_offline_qc_command_returns_nonzero_on_errors(tmp_path) -> None:
    manifest_path, manifest = _write_manifest(tmp_path)
    manifest.pop("gesture_options")
    collection_session.write_manifest(manifest_path=manifest_path, manifest=manifest)

    result = runner.invoke(
        app,
        [
            "collection",
            "rd",
            "offline-qc",
            "--manifest",
            str(manifest_path),
        ],
    )

    assert result.exit_code == 1
    assert "Offline QC Summary" in result.output
    assert "errors: 1" in result.output


def test_collection_offline_qc_all_command_returns_nonzero_on_errors(tmp_path) -> None:
    _write_session_manifest(tmp_path, session_id="session_a")
    manifest_path, manifest = _write_session_manifest(tmp_path, session_id="session_b")
    manifest.pop("gesture_options")
    collection_session.write_manifest(manifest_path=manifest_path, manifest=manifest)

    result = runner.invoke(
        app,
        [
            "collection",
            "rd",
            "offline-qc-all",
            "--sessions-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "Offline QC Validation Summary" in result.output
    assert "checked_manifests: 2" in result.output


def _write_manifest(
    tmp_path: Path,
    *,
    raw_capture: bytes | None = None,
    marked_window: dict[str, float] | None = None,
) -> tuple[Path, dict[str, object]]:
    raw_uart_path = tmp_path / "take01_raw_uart.bin"
    raw_uart_path.write_bytes(
        _build_packet(frame_number=1, tlv_types=[1])
        if raw_capture is None
        else raw_capture
    )

    resolved_marked_window = (
        {
            "start_s": 1.0,
            "end_s": 2.2,
        }
        if marked_window is None and raw_capture is None
        else marked_window
    )
    manifest = _build_valid_manifest(
        raw_uart_path=raw_uart_path,
        marked_window=resolved_marked_window,
    )
    manifest_path = tmp_path / "manifest.json"
    collection_session.write_manifest(manifest_path=manifest_path, manifest=manifest)
    return manifest_path, manifest


def _write_background_manifest(
    tmp_path: Path,
    *,
    raw_capture: bytes = b"abcdef",
    recorded_bytes: int | None = None,
) -> tuple[Path, dict[str, object]]:
    background_dir = tmp_path / "background"
    background_dir.mkdir(parents=True, exist_ok=True)
    raw_uart_path = background_dir / collection_session.BACKGROUND_RAW_UART_FILENAME
    raw_uart_path.write_bytes(raw_capture)

    manifest = _build_valid_manifest(
        raw_uart_path=raw_uart_path,
        marked_window=None,
    )
    manifest["collection_type"] = collection_session.COLLECTION_TYPE_WHITE_SPACE
    manifest["background_plan"] = {
        "sample_ratio": 2.0,
        "default_recording_duration_multiplier": 1.25,
        "window_duration_s": 5.0,
        "target_segment_count": 2,
        "planned_recording_duration_s": 12.5,
        "selection_policy": "random_after_capture",
        "save_policy": "keep_full_capture",
        "selection_seed": 7,
    }
    manifest["background_capture"] = {
        "status": collection_session.BACKGROUND_CAPTURE_STATUS_COMPLETED,
        "raw_uart_path": str(raw_uart_path),
        "started_at": "2026-04-12T09:00:00+08:00",
        "completed_at": "2026-04-12T09:00:12+08:00",
        "interrupted_at": None,
        "recording_duration_s": 12.5,
        "recorded_bytes": len(raw_capture)
        if recorded_bytes is None
        else recorded_bytes,
    }
    manifest["takes"] = []

    manifest_path = tmp_path / "manifest.json"
    collection_session.write_manifest(manifest_path=manifest_path, manifest=manifest)
    return manifest_path, manifest


def _write_session_manifest(
    sessions_root: Path,
    *,
    session_id: str,
    raw_capture: bytes | None = None,
    marked_window: dict[str, float] | None = None,
) -> tuple[Path, dict[str, object]]:
    session_dir = sessions_root / session_id
    session_dir.mkdir(parents=True, exist_ok=False)
    return _write_manifest(
        session_dir,
        raw_capture=raw_capture,
        marked_window=marked_window,
    )


def _build_valid_manifest(
    *,
    raw_uart_path: Path,
    marked_window: dict[str, float] | None,
) -> dict[str, object]:
    return {
        "schema_version": collection_session.SESSION_SCHEMA_VERSION,
        "session_id": "20260412_090000_alice_swipe_left",
        "collection_type": collection_session.COLLECTION_TYPE_GESTURE,
        "subject_name": "alice",
        "hand": "right",
        "distance_m": 0.5,
        "angle_deg": 0.0,
        "environment": "office_lab",
        "operator_name": "operator_a",
        "note": "pilot",
        "radar_id": "radar_01",
        "firmware_id": "fw_01",
        "firmware_config_id": "stub_mmwave_cfg",
        "companion_profile_id": "rd_background_default",
        "background_plan": None,
        "background_capture": None,
        "gesture": "swipe_left",
        "gesture_options": ["swipe_left", "swipe_right"],
        "environment_options": ["office_lab", "hallway"],
        "cli_port": "/dev/cli",
        "data_port": "/dev/data",
        "data_baudrate": 921_600,
        "takes": [
            {
                "take_index": 1,
                "take_id": "take01",
                "status": collection_session.TAKE_STATUS_ACCEPTED,
                "raw_uart_path": str(raw_uart_path),
                "accepted_at": "2026-04-12T09:00:00+08:00",
                "capture_window": {
                    "start_s": 0.0,
                    "end_s": 5.0,
                },
                "target_window": {
                    "start_s": 1.0,
                    "end_s": 2.5,
                },
                "marked_window": marked_window,
            }
        ],
        "config_snapshot": {
            "schema_version": "collection_rd_config_v3",
            "config_id": "stub_profile",
            "label": "Stub profile",
            "description": "Stub manifest used for offline QC tests.",
            "default_companion_profile_id": "rd_background_default",
            "batch_size": 1,
            "global": {
                "config_id": "stub_global",
            },
            "runtime": {
                "capture_window_duration_s": 5.0,
                "countdown_duration_s": 5.0,
                "marked_window_end_grace_s": 0.25,
                "end_mark_key": "space",
            },
            "defaults": {
                "hand": "right",
                "distance_m": 0.5,
                "angle_deg": 0.0,
                "environment": "office_lab",
                "radar_id": "radar_01",
                "firmware_id": "fw_01",
                "firmware_config_id": "stub_mmwave_cfg",
            },
            "serial": {
                "cli_port": None,
                "data_port": None,
                "cli_baudrate": 115_200,
                "data_baudrate": 921_600,
            },
            "options": {
                "gestures": ["swipe_left", "swipe_right"],
                "environments": ["office_lab", "hallway"],
            },
            "gesture_target_durations": {
                "swipe_left": 1.5,
                "swipe_right": 1.7,
            },
        },
    }


def _build_packet(frame_number: int, tlv_types: list[int]) -> bytes:
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
