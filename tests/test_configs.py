from __future__ import annotations

from pathlib import Path

from vassago.configs.catalog import clear_catalog_cache
from vassago.configs.catalog import load_catalog
from vassago.configs.metadata import parse_metadata_header
from vassago.configs.mmwave_cfg_integrity import compute_mmwave_cfg_digest
from vassago.configs.mmwave_cfg_integrity import validate_mmwave_cfg_integrity
from vassago.configs.models import CatalogEntry
from vassago.configs.models import ConfigKind
from vassago.configs.models import ValidationLevel
from vassago.configs.validation import validate_all_configs
from vassago.configs.validation_contract import ValidationContext
from vassago.configs.validation_contract import ValidationMessage
from vassago.firmware.mmwave.config_validation import validate_cfg

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_CFG_PATH = REPO_ROOT / "configs/firmware/mmwave/baseline_pointcloud.cfg"


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
            kind=ConfigKind.MMWAVE_CFG,
            config_id="rd_candidate",
        ).path.name
        == "rd_candidate.cfg"
    )


def test_validate_all_configs_has_no_errors_for_repo_baseline() -> None:
    messages = validate_all_configs()

    assert not [
        message for message in messages if message.level == ValidationLevel.ERROR
    ]


def test_validate_all_configs_accepts_custom_checks() -> None:
    expected_message = ValidationMessage(
        level=ValidationLevel.WARN,
        path=BASELINE_CFG_PATH,
        message="custom check ran",
    )

    def custom_check(context: ValidationContext) -> list[ValidationMessage]:
        return [expected_message]

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
    path.write_text(
        "\n".join(
            (
                'schema_version = "mmwave_cfg_integrity_v1"',
                "",
                "[[cfg]]",
                f'config_id = "{config_id}"',
                f'sha256 = "{sha256}"',
                "",
            )
        ),
        encoding="utf-8",
    )
    return path
