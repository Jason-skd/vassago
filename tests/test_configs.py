from __future__ import annotations

from pathlib import Path

from vassago.configs.catalog import clear_catalog_cache
from vassago.configs.catalog import load_catalog
from vassago.configs.models import ConfigKind
from vassago.configs.models import ValidationLevel
from vassago.configs.validation import validate_all_configs
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
