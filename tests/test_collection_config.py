from __future__ import annotations

import pytest

from vassago.collection.rd import config as collection_config


def test_get_collection_profile_loads_sample_config() -> None:
    profile = collection_config.get_collection_profile("rd_phase1_default")
    first_gesture = profile.gestures[0]
    expected_duration = profile.gesture_target_durations[0].target_window_duration_s

    assert profile.config_id == "rd_phase1_default"
    assert profile.global_config_id == "rd_global_default"
    assert profile.capture_window_duration_s == 5.0
    assert profile.countdown_duration_s == 5.0
    assert profile.marked_window_end_grace_s == 0.25
    assert profile.end_mark_key == "space"
    assert profile.default_firmware_config_id == "rd_pointcloud_dual"
    assert (
        profile.target_window_duration_for(gesture=first_gesture) == expected_duration
    )


def test_collection_profile_snapshot_carries_full_effective_config() -> None:
    profile = collection_config.get_collection_profile("rd_phase1_default")
    first_duration = profile.gesture_target_durations[0]

    snapshot = profile.as_snapshot()
    runtime = snapshot["runtime"]
    serial = snapshot["serial"]
    gesture_target_durations = snapshot["gesture_target_durations"]

    assert isinstance(runtime, dict)
    assert isinstance(serial, dict)
    assert isinstance(gesture_target_durations, dict)

    assert snapshot["config_id"] == "rd_phase1_default"
    assert snapshot["batch_size"] == profile.batch_size
    assert snapshot["global"] == {"config_id": "rd_global_default"}
    defaults = snapshot["defaults"]
    assert isinstance(defaults, dict)
    assert defaults["firmware_config_id"] == "rd_pointcloud_dual"
    assert runtime["capture_window_duration_s"] == 5.0
    assert runtime["countdown_duration_s"] == 5.0
    assert serial["data_baudrate"] == 921_600
    assert (
        gesture_target_durations[first_duration.gesture]
        == first_duration.target_window_duration_s
    )


def test_collection_profile_rejects_legacy_firmware_section(tmp_path) -> None:
    profile_path = tmp_path / "legacy_firmware.toml"
    profile_path.write_text(
        """# --- vassago:meta ---
# config_kind = "collection_rd_profile"
# config_id = "legacy_firmware_profile"
# label = "Legacy Firmware Profile"
# description = "Should fail because [firmware] is no longer supported."
# lifecycle = "active"
# ---
schema_version = "collection_rd_profile_v3"
batch_size = 1

[global]
config_id = "rd_global_default"

[firmware]
default_config_id = "rd_candidate"

[defaults]
hand = "right"
distance_m = 0.5
angle_deg = 0.0
environment = "office_lab"
radar_id = "rd_aop_01"
firmware_id = "rd_phase1_uart"

[options]
gestures = ["wave"]
environments = ["office_lab"]

[gesture_target_durations]
wave = 1.0
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="defaults\\.firmware_config_id"):
        collection_config.load_collection_profile(profile_path)
