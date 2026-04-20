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
            firmware_config_id="rd_candidate",
            cli_port="/dev/cli",
            data_port="/dev/data",
            data_baudrate=921_600,
        ),
        sessions_root=tmp_path,
    )

    loaded_manifest = collection_session.load_manifest(manifest_path)
    config_snapshot = loaded_manifest["config_snapshot"]
    assert isinstance(config_snapshot, dict)
    takes = loaded_manifest["takes"]
    assert isinstance(takes, list)
    first_take = takes[0]
    assert isinstance(first_take, dict)

    assert manifest_path.exists()
    assert manifest["schema_version"] == collection_session.SESSION_SCHEMA_VERSION
    assert (
        loaded_manifest["collection_type"] == collection_session.COLLECTION_TYPE_GESTURE
    )
    assert loaded_manifest["subject_name"] == "alice"
    assert "config_id" not in loaded_manifest
    assert loaded_manifest["firmware_config_id"] == "rd_candidate"
    assert loaded_manifest["companion_profile_id"] == "rd_background_default"
    assert loaded_manifest["background_plan"] is None
    assert loaded_manifest["gesture_options"] == list(profile.gestures)
    assert loaded_manifest["environment_options"] == list(profile.environments)
    assert len(takes) == profile.batch_size
    assert config_snapshot["batch_size"] == profile.batch_size
    assert config_snapshot["default_companion_profile_id"] == "rd_background_default"
    defaults = config_snapshot["defaults"]
    assert isinstance(defaults, dict)
    assert defaults["firmware_config_id"] == profile.default_firmware_config_id
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
            firmware_config_id=profile.default_firmware_config_id,
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


def test_load_manifest_backfills_legacy_companion_contract(tmp_path) -> None:
    profile = collection_config.get_collection_profile("rd_phase1_default")
    manifest_path, manifest = collection_session.initialize_session(
        session_input=collection_session.SessionInitInput(
            profile=profile,
            subject_name="alice",
            hand="right",
            distance_m=0.5,
            angle_deg=0.0,
            environment=profile.defaults.environment,
            operator_name="operator_a",
            note=None,
            radar_id="radar_01",
            firmware_id="fw_01",
            gesture=profile.gestures[0],
            firmware_config_id=profile.default_firmware_config_id,
            cli_port="/dev/cli",
            data_port="/dev/data",
            data_baudrate=921_600,
        ),
        sessions_root=tmp_path,
    )
    manifest.pop("collection_type")
    manifest.pop("companion_profile_id")
    manifest.pop("background_plan")
    config_snapshot = manifest["config_snapshot"]
    assert isinstance(config_snapshot, dict)
    config_snapshot.pop("default_companion_profile_id")
    collection_session.write_manifest(manifest_path=manifest_path, manifest=manifest)

    loaded_manifest = collection_session.load_manifest(manifest_path)
    loaded_snapshot = loaded_manifest["config_snapshot"]

    assert (
        loaded_manifest["collection_type"] == collection_session.COLLECTION_TYPE_GESTURE
    )
    assert loaded_manifest["companion_profile_id"] == "rd_background_default"
    assert loaded_manifest["background_plan"] is None
    assert isinstance(loaded_snapshot, dict)
    assert loaded_snapshot["default_companion_profile_id"] == "rd_background_default"
