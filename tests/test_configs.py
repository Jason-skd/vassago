from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vassago.cli import app
from vassago.configs.catalog import clear_catalog_cache
from vassago.configs.catalog import load_catalog
from vassago.configs.metadata import parse_metadata_header
from vassago.configs.mmwave_cfg_integrity import clear_mmwave_cfg_integrity_cache
from vassago.configs.mmwave_cfg_integrity import compute_mmwave_cfg_digest
from vassago.configs.mmwave_cfg_integrity import load_mmwave_cfg_integrity_registry
from vassago.configs.mmwave_cfg_integrity import validate_mmwave_cfg_integrity
from vassago.configs.models import CatalogEntry
from vassago.configs.models import ConfigKind
from vassago.configs.models import ValidationLevel
from vassago.configs.paths import MMWAVE_CFG_INTEGRITY_PATH
from vassago.configs.paths import resolve_repo_path
from vassago.configs.validation import run_config_discovery
from vassago.configs.validation import validate_all_configs
from vassago.configs.validation_contract import ValidationContext
from vassago.configs.validation_contract import ValidationMessage
from vassago.configs.validation_contract import ValidationReport
from vassago.firmware.mmwave.config_validation import validate_cfg

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_CFG_PATH = REPO_ROOT / "configs/firmware/mmwave/baseline_pointcloud.cfg"
RD_CANDIDATE_CFG_PATH = REPO_ROOT / "configs/firmware/mmwave/rd_candidate.cfg"
RD_POINTCLOUD_DUAL_CFG_PATH = (
    REPO_ROOT / "configs/firmware/mmwave/rd_pointcloud_dual.cfg"
)
runner = CliRunner()


def test_catalog_discovers_repo_managed_configs() -> None:
    clear_catalog_cache()
    catalog = load_catalog()

    assert (
        catalog.require_entry(
            kind=ConfigKind.COLLECTION_RD_GLOBAL,
            config_id="rd_global_default",
        ).path.name
        == "global.toml"
    )
    assert (
        catalog.require_entry(
            kind=ConfigKind.COLLECTION_RD_PROFILE,
            config_id="rd_phase1_default",
        ).path.name
        == "rd_phase1_default.toml"
    )
    assert (
        catalog.require_entry(
            kind=ConfigKind.COLLECTION_RD_COMPANION_PROFILE,
            config_id="rd_background_default",
        ).path.name
        == "rd_background_default.toml"
    )
    assert (
        catalog.require_entry(
            kind=ConfigKind.MMWAVE_CFG,
            config_id="rd_candidate",
        ).path.name
        == "rd_candidate.cfg"
    )


def test_validate_all_configs_has_no_errors_for_repo_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_integrity_registry(tmp_path, monkeypatch)
    messages = validate_all_configs()

    assert not [
        message for message in messages if message.level == ValidationLevel.ERROR
    ]


def test_run_config_discovery_builds_catalog_without_errors() -> None:
    result = run_config_discovery()

    assert result.report.has_errors is False
    assert (
        result.catalog.require_entry(
            kind=ConfigKind.MMWAVE_CFG,
            config_id="rd_candidate",
        ).path.name
        == "rd_candidate.cfg"
    )


def test_configs_list_command_renders_known_entries() -> None:
    result = runner.invoke(app, ["configs", "list", "--kind", "mmwave_cfg"])

    assert result.exit_code == 0
    assert "Managed Config Catalog" in result.output
    assert "rd_candidate" in result.output


def test_configs_validate_command_succeeds_for_repo_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_integrity_registry(tmp_path, monkeypatch)
    result = runner.invoke(app, ["configs", "validate"])

    assert result.exit_code == 0
    assert "Config Validation Summary" in result.output
    assert "result: pass" in result.output


def test_configs_validate_discovery_command_succeeds_for_repo_baseline() -> None:
    result = runner.invoke(app, ["configs", "validate-discovery"])

    assert result.exit_code == 0
    assert "Config Discovery Summary" in result.output
    assert "result: pass" in result.output


def test_configs_validate_mmwave_cfg_integrity_command_succeeds_for_repo_baseline() -> (
    None
):
    result = runner.invoke(app, ["configs", "validate-mmwave-cfg-integrity"])

    assert result.exit_code == 0
    assert "mmWave cfg Integrity Summary" in result.output
    assert "result: pass" in result.output


def test_record_missing_mmwave_cfg_integrity_command_appends_new_cfg_only(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "integrity.toml"
    _write_integrity_registry_entries(
        registry_path,
        entries=(
            (
                "baseline_pointcloud",
                compute_mmwave_cfg_digest(BASELINE_CFG_PATH),
            ),
            (
                "rd_candidate",
                compute_mmwave_cfg_digest(RD_CANDIDATE_CFG_PATH),
            ),
        ),
    )

    result = runner.invoke(
        app,
        [
            "configs",
            "record-missing-mmwave-cfg-integrity",
            "--registry-path",
            str(registry_path),
        ],
    )

    registry = load_mmwave_cfg_integrity_registry(registry_path)

    assert result.exit_code == 0
    assert "added_config_ids: rd_pointcloud_dual" in result.output
    assert registry["rd_candidate"].sha256 == compute_mmwave_cfg_digest(
        RD_CANDIDATE_CFG_PATH
    )
    assert sorted(registry) == [
        "baseline_pointcloud",
        "rd_candidate",
        "rd_pointcloud_dual",
    ]


def test_validate_all_configs_appends_missing_mmwave_cfg_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_path = tmp_path / "integrity.toml"
    _write_integrity_registry_entries(
        registry_path,
        entries=(
            (
                "baseline_pointcloud",
                compute_mmwave_cfg_digest(BASELINE_CFG_PATH),
            ),
            (
                "rd_candidate",
                compute_mmwave_cfg_digest(RD_CANDIDATE_CFG_PATH),
            ),
        ),
    )

    monkeypatch.setattr(
        "vassago.configs.mmwave_cfg_integrity.MMWAVE_CFG_INTEGRITY_PATH",
        registry_path,
    )
    clear_mmwave_cfg_integrity_cache()

    messages = validate_all_configs()
    registry = load_mmwave_cfg_integrity_registry(registry_path)

    assert not [
        message for message in messages if message.level == ValidationLevel.ERROR
    ]
    assert registry["rd_pointcloud_dual"].sha256 == compute_mmwave_cfg_digest(
        RD_POINTCLOUD_DUAL_CFG_PATH
    )


def test_validate_all_configs_accepts_custom_checks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _use_temp_integrity_registry(tmp_path, monkeypatch)
    expected_message = ValidationMessage(
        level=ValidationLevel.WARN,
        path=BASELINE_CFG_PATH,
        message="custom check ran",
    )

    def custom_check(context: ValidationContext) -> ValidationReport:
        return ValidationReport.from_messages([expected_message])

    messages = validate_all_configs(checks=(custom_check,))

    assert messages == [expected_message]


def test_mmwave_cfg_validation_warns_on_bpmcfg(tmp_path: Path) -> None:
    config_text = BASELINE_CFG_PATH.read_text(encoding="utf-8").replace(
        "\nsensorStart\n",
        "\nbpmCfg -1 0 0 0\n\nsensorStart\n",
    )
    config_path = tmp_path / "bpm_warn.cfg"
    config_path.write_text(config_text, encoding="utf-8")

    issues = validate_cfg(config_path)

    assert any(
        issue.level == ValidationLevel.WARN and "bpmCfg" in issue.message
        for issue in issues
    )
    assert not [issue for issue in issues if issue.level == ValidationLevel.ERROR]


def test_mmwave_cfg_integrity_allows_path_migration(tmp_path: Path) -> None:
    migrated_path = tmp_path / "nested" / "baseline_pointcloud.cfg"
    migrated_path.parent.mkdir(parents=True)
    migrated_path.write_text(
        BASELINE_CFG_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    entry = CatalogEntry(
        metadata=parse_metadata_header(migrated_path),
        path=migrated_path,
    )
    registry_path = _write_integrity_registry(
        tmp_path / "integrity.toml",
        config_id=entry.config_id,
        sha256=compute_mmwave_cfg_digest(BASELINE_CFG_PATH),
    )

    messages = validate_mmwave_cfg_integrity([entry], registry_path=registry_path)

    assert not messages


def test_mmwave_cfg_integrity_rejects_cfg_content_changes(tmp_path: Path) -> None:
    changed_text = BASELINE_CFG_PATH.read_text(encoding="utf-8").replace(
        "frameCfg 0 2 32 0 33 1 0",
        "frameCfg 0 2 64 0 33 1 0",
    )
    changed_path = tmp_path / "baseline_pointcloud.cfg"
    changed_path.write_text(changed_text, encoding="utf-8")

    entry = CatalogEntry(
        metadata=parse_metadata_header(changed_path),
        path=changed_path,
    )
    registry_path = _write_integrity_registry(
        tmp_path / "integrity.toml",
        config_id=entry.config_id,
        sha256=compute_mmwave_cfg_digest(BASELINE_CFG_PATH),
    )

    messages = validate_mmwave_cfg_integrity([entry], registry_path=registry_path)

    assert len(messages) == 1
    assert messages[0].level == ValidationLevel.ERROR
    assert "content digest mismatch" in messages[0].message
    assert "must not change" in messages[0].message


def _write_integrity_registry(path: Path, *, config_id: str, sha256: str) -> Path:
    return _write_integrity_registry_entries(
        path,
        entries=((config_id, sha256),),
    )


def _use_temp_integrity_registry(tmp_path: Path, monkeypatch) -> Path:
    registry_path = tmp_path / "mmwave_cfg_integrity.toml"
    registry_path.write_text(
        resolve_repo_path(MMWAVE_CFG_INTEGRITY_PATH).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "vassago.configs.mmwave_cfg_integrity.MMWAVE_CFG_INTEGRITY_PATH",
        registry_path,
    )
    clear_mmwave_cfg_integrity_cache()
    return registry_path


def _write_integrity_registry_entries(
    path: Path,
    *,
    entries: tuple[tuple[str, str], ...],
) -> Path:
    lines = ['schema_version = "mmwave_cfg_integrity_v1"', ""]
    for config_id, sha256 in entries:
        lines.extend(
            (
                "[[cfg]]",
                f'config_id = "{config_id}"',
                f'sha256 = "{sha256}"',
                "",
            )
        )
    path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )
    return path
