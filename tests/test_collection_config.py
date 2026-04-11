from __future__ import annotations

from vassago.collection.rd import config as collection_config


def test_get_collection_profile_loads_sample_config() -> None:
    profile = collection_config.get_collection_profile("rd_phase1_default")

    assert profile.config_id == "rd_phase1_default"
    assert profile.capture_duration_s == 5.0
    assert profile.batch_size == 12
    assert profile.firmware_config_path.name == "rd_phase1_uart.cfg"
    assert profile.target_window_for(
        gesture="swipe_left",
        speed="normal",
    ) == collection_config.WindowRange(start_s=1.2, end_s=2.8)


def test_collection_profile_snapshot_carries_full_effective_config() -> None:
    profile = collection_config.get_collection_profile("rd_phase1_default")

    snapshot = profile.as_snapshot()

    assert snapshot["config_id"] == "rd_phase1_default"
    assert snapshot["firmware"] == {
        "config_id": "rd_candidate",
        "config_path": "configs/rd_phase1_uart.cfg",
    }
    assert snapshot["serial"]["data_baudrate"] == 921_600
    assert len(snapshot["target_windows"]) == 12
