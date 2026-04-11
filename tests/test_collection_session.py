from __future__ import annotations

from vassago.collection.rd import config as collection_config
from vassago.collection.rd import session as collection_session


def test_initialize_session_persists_manifest_with_config_snapshot(tmp_path) -> None:
    profile = collection_config.get_collection_profile("rd_phase1_default")

    manifest_path, manifest = collection_session.initialize_session(
        session_input=collection_session.SessionInitInput(
            profile=profile,
            subject_name="alice",
            hand="right",
            distance_m=0.5,
            angle_deg=0.0,
            environment="office_lab",
            operator_name="operator_a",
            note="pilot",
            radar_id="radar_01",
            firmware_id="fw_01",
            gesture="swipe_left",
            speed="normal",
            cli_port="/dev/cli",
            data_port="/dev/data",
            data_baudrate=921_600,
        ),
        sessions_root=tmp_path,
    )

    loaded_manifest = collection_session.load_manifest(manifest_path)

    assert manifest_path.exists()
    assert manifest["schema_version"] == collection_session.SESSION_SCHEMA_VERSION
    assert loaded_manifest["subject_name"] == "alice"
    assert loaded_manifest["config_id"] == "rd_phase1_default"
    assert loaded_manifest["config_snapshot"]["firmware"]["config_path"] == (
        "configs/rd_phase1_uart.cfg"
    )
    assert loaded_manifest["takes"][0]["capture_window"] == {
        "start_s": 0.0,
        "end_s": 5.0,
    }
    assert loaded_manifest["takes"][0]["target_window"] == {
        "start_s": 1.2,
        "end_s": 2.8,
    }


def test_list_unfinished_sessions_returns_pending_manifest(tmp_path) -> None:
    profile = collection_config.get_collection_profile("rd_phase1_default")
    collection_session.initialize_session(
        session_input=collection_session.SessionInitInput(
            profile=profile,
            subject_name="alice",
            hand="right",
            distance_m=0.5,
            angle_deg=0.0,
            environment="office_lab",
            operator_name="operator_a",
            note=None,
            radar_id="radar_01",
            firmware_id="fw_01",
            gesture="swipe_left",
            speed="normal",
            cli_port="/dev/cli",
            data_port="/dev/data",
            data_baudrate=921_600,
        ),
        sessions_root=tmp_path,
    )

    summaries = collection_session.list_unfinished_sessions(sessions_root=tmp_path)

    assert len(summaries) == 1
    assert summaries[0].subject_name == "alice"
    assert summaries[0].remaining_take_count == 12
