from __future__ import annotations

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
    assert profile.firmware_config_id == "rd_candidate"
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
    assert snapshot["global"] == {"config_id": "rd_global_default"}
    assert snapshot["firmware"] == {
        "config_id": "rd_candidate",
    }
    assert runtime["capture_window_duration_s"] == 5.0
    assert runtime["countdown_duration_s"] == 5.0
    assert serial["data_baudrate"] == 921_600
    assert (
        gesture_target_durations[first_duration.gesture]
        == first_duration.target_window_duration_s
    )
