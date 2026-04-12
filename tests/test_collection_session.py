from __future__ import annotations

from vassago.collection.rd import config as collection_config
from vassago.collection.rd import session as collection_session


def test_initialize_session_persists_manifest_with_config_snapshot(tmp_path) -> None:
    profile = collection_config.get_collection_profile("rd_phase1_default")
    selected_gesture = profile.gestures[0]
    selected_environment = profile.defaults.environment

    manifest_path, manifest = collection_session.initialize_session(
        session_input=collection_session.SessionInitInput(
            profile=profile,
            subject_name="alice",
            hand="right",
            distance_m=0.5,
            angle_deg=0.0,
            environment=selected_environment,
            operator_name="operator_a",
            note="pilot",
            radar_id="radar_01",
            firmware_id="fw_01",
            gesture=selected_gesture,
            cli_port="/dev/cli",
            data_port="/dev/data",
            data_baudrate=921_600,
        ),
        sessions_root=tmp_path,
    )

    loaded_manifest = collection_session.load_manifest(manifest_path)
    config_snapshot = loaded_manifest["config_snapshot"]
    assert isinstance(config_snapshot, dict)
    firmware = config_snapshot["firmware"]
    assert isinstance(firmware, dict)
    takes = loaded_manifest["takes"]
    assert isinstance(takes, list)
    first_take = takes[0]
    assert isinstance(first_take, dict)

    assert manifest_path.exists()
    assert manifest["schema_version"] == collection_session.SESSION_SCHEMA_VERSION
    assert loaded_manifest["subject_name"] == "alice"
    assert loaded_manifest["config_id"] == "rd_phase1_default"
    assert loaded_manifest["batch_size"] == profile.batch_size
    assert loaded_manifest["gesture_options"] == list(profile.gestures)
    assert loaded_manifest["environment_options"] == list(profile.environments)
    assert config_snapshot["batch_size"] == profile.batch_size
    assert firmware["config_id"] == "rd_candidate"
    assert first_take["capture_window"] is None
    assert first_take["target_window"] is None
    assert first_take["marked_window"] is None


def test_list_unfinished_sessions_returns_pending_manifest(tmp_path) -> None:
    profile = collection_config.get_collection_profile("rd_phase1_default")
    selected_gesture = profile.gestures[0]
    selected_environment = profile.defaults.environment
    collection_session.initialize_session(
        session_input=collection_session.SessionInitInput(
            profile=profile,
            subject_name="alice",
            hand="right",
            distance_m=0.5,
            angle_deg=0.0,
            environment=selected_environment,
            operator_name="operator_a",
            note=None,
            radar_id="radar_01",
            firmware_id="fw_01",
            gesture=selected_gesture,
            cli_port="/dev/cli",
            data_port="/dev/data",
            data_baudrate=921_600,
        ),
        sessions_root=tmp_path,
    )

    summaries = collection_session.list_unfinished_sessions(sessions_root=tmp_path)

    assert len(summaries) == 1
    assert summaries[0].subject_name == "alice"
    assert summaries[0].gesture == selected_gesture
    assert summaries[0].remaining_take_count == profile.batch_size
