from __future__ import annotations

from pathlib import Path
from typing import Self

from typer.testing import CliRunner

from vassago.cli import app
from vassago.collection.rd import capture as collection_capture
from vassago.collection.rd import cli as collection_cli
from vassago.collection.rd import config as collection_config
from vassago.collection.rd import quick_qc as collection_quick_qc
from vassago.collection.rd import session as collection_session

runner = CliRunner()


def test_collection_list_configs_command_renders_sample_profile(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "cfg_short.toml"
    monkeypatch.setattr(
        "vassago.collection.rd.cli.collection_config.list_collection_profiles",
        lambda: [
            collection_config.CollectionProfile(
                config_id="cfg_short",
                path=config_path,
                label="Short",
                description="Short description",
                global_config_id="rd_global_default",
                batch_size=1,
                firmware_config_id="rd_candidate",
                defaults=collection_config.CollectionDefaults(
                    hand="right",
                    distance_m=0.5,
                    angle_deg=0.0,
                    environment="office_lab",
                    radar_id="radar_01",
                    firmware_id="fw_01",
                ),
                serial=collection_config.CollectionSerialDefaults(
                    cli_port=None,
                    data_port=None,
                    cli_baudrate=115_200,
                    data_baudrate=921_600,
                ),
                gestures=("swipe_left",),
                environments=("office_lab",),
                gesture_target_durations=(
                    collection_config.GestureTargetDuration(
                        gesture="swipe_left",
                        target_window_duration_s=1.6,
                    ),
                ),
                capture_window_duration_s=5.0,
                countdown_duration_s=5.0,
                marked_window_end_grace_s=0.25,
                end_mark_key="space",
            )
        ],
    )

    result = runner.invoke(app, ["collection", "rd", "list-configs"])

    assert result.exit_code == 0
    assert "cfg_short" in result.output


def test_collection_init_session_command_writes_manifest(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "collection",
            "rd",
            "init-session",
            "--config-id",
            "rd_phase1_default",
            "--subject-name",
            "alice",
            "--gesture",
            "swipe_left",
            "--environment",
            "office_lab",
            "--operator-name",
            "operator_a",
            "--radar-id",
            "radar_01",
            "--firmware-id",
            "fw_01",
            "--cli-port",
            "/dev/cli",
            "--data-port",
            "/dev/data",
            "--sessions-root",
            str(tmp_path),
            "--no-interactive",
        ],
    )

    manifests = list(Path(tmp_path).glob("*/manifest.json"))

    assert result.exit_code == 0
    assert len(manifests) == 1
    assert "Collection Session Summary" in result.output


def test_interactive_init_session_prompts_operator_name_without_default(
    tmp_path,
    monkeypatch,
) -> None:
    profile = collection_config.get_collection_profile("rd_phase1_default")
    prompt_defaults: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        "vassago.collection.rd.cli.sys.stdin.isatty",
        lambda: True,
    )
    monkeypatch.setattr(
        "vassago.collection.rd.cli._resolve_profile",
        lambda **_kwargs: profile,
    )
    monkeypatch.setattr(
        "vassago.collection.rd.cli._resolve_gesture",
        lambda **_kwargs: "swipe_left",
    )
    monkeypatch.setattr(
        "vassago.collection.rd.cli._resolve_ports",
        lambda **_kwargs: ("/dev/cli", "/dev/data"),
    )

    def fake_prompt_for_required_text(
        *, message: str, default: str | None = None
    ) -> str:
        prompt_defaults.append((message, default))
        values = {
            "subject_name": "alice",
            "operator_name": "operator_b",
            "radar_id": "radar_01",
            "firmware_id": "fw_01",
        }
        return values[message]

    monkeypatch.setattr(
        "vassago.collection.rd.cli.collection_ui.prompt_for_required_text",
        fake_prompt_for_required_text,
    )
    monkeypatch.setattr(
        "vassago.collection.rd.cli.collection_ui.prompt_for_choice",
        lambda **kwargs: kwargs.get("default") or kwargs["choices"][0],
    )
    monkeypatch.setattr(
        "vassago.collection.rd.cli.collection_ui.prompt_for_optional_float",
        lambda **kwargs: kwargs.get("default"),
    )
    monkeypatch.setattr(
        "vassago.collection.rd.cli.collection_ui.prompt_for_optional_text",
        lambda **_kwargs: None,
    )

    collection_cli.handle_init_session(
        config=None,
        config_id="rd_phase1_default",
        subject_name=None,
        hand=None,
        distance_m=None,
        angle_deg=None,
        environment=None,
        operator_name=None,
        note=None,
        radar_id=None,
        firmware_id=None,
        gesture=None,
        cli_port=None,
        data_port=None,
        data_baudrate=None,
        sessions_root=tmp_path,
        run_after_init=False,
        interactive=True,
    )

    assert ("operator_name", None) in prompt_defaults


def test_run_session_accepts_take_and_updates_manifest(tmp_path, monkeypatch) -> None:
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
            note=None,
            radar_id="radar_01",
            firmware_id="fw_01",
            gesture="swipe_left",
            cli_port="/dev/cli",
            data_port="/dev/data",
            data_baudrate=921_600,
        ),
        sessions_root=tmp_path,
    )
    manifest["batch_size"] = 1
    takes = manifest["takes"]
    assert isinstance(takes, list)
    manifest["takes"] = takes[:1]
    collection_session.write_manifest(manifest_path=manifest_path, manifest=manifest)

    class FakeSerial:
        def __init__(self, *_args, **kwargs) -> None:
            self.timeout = kwargs.get("timeout", 0.0)

        def __enter__(self) -> Self:
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def reset_input_buffer(self) -> None:
            return None

        def read(self, _size: int) -> bytes:
            return b""

    monkeypatch.setattr(
        "vassago.collection.rd.capture._configure_radar",
        lambda _manifest: None,
    )
    monkeypatch.setattr(
        "vassago.collection.rd.capture.serial.Serial",
        FakeSerial,
    )
    monkeypatch.setattr(
        "vassago.collection.rd.capture.capture_take",
        lambda _connection, **_kwargs: collection_capture.TakeCaptureResult(
            raw_capture=b"raw",
            capture_window=collection_config.WindowRange(0.0, 5.0),
            target_window=collection_config.WindowRange(1.2, 2.8),
            marked_window=collection_config.WindowRange(1.2, 2.4),
        ),
    )
    monkeypatch.setattr(
        "vassago.collection.rd.capture.quick_qc.evaluate_capture",
        lambda **_kwargs: collection_quick_qc.QuickQcDecision(
            accepted=True,
            reasons=(),
        ),
    )
    monkeypatch.setattr(
        "vassago.collection.rd.capture.collection_ui.render_take_state",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "vassago.collection.rd.capture.collection_ui.render_capture_summary",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "vassago.collection.rd.capture.collection_ui.render_quick_qc",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "vassago.collection.rd.capture.collection_ui.prompt_take_action",
        lambda **_kwargs: "start",
    )
    monkeypatch.setattr(
        "vassago.collection.rd.capture.collection_ui.prompt_take_decision",
        lambda **_kwargs: "accept",
    )

    summary = collection_capture.run_session(manifest_path)
    updated_manifest = collection_session.load_manifest(manifest_path)
    updated_takes = updated_manifest["takes"]
    assert isinstance(updated_takes, list)
    first_take = updated_takes[0]
    assert isinstance(first_take, dict)

    assert summary.session_status == collection_session.SESSION_STATUS_COMPLETED
    assert summary.accepted_take_count == 1
    assert first_take["status"] == collection_session.TAKE_STATUS_ACCEPTED
    assert first_take["raw_uart_path"] is not None
    assert first_take["target_window"] == {
        "start_s": 1.2,
        "end_s": 2.8,
    }
