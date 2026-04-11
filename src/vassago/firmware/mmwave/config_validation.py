"""Semantic validation for repository-managed mmWave cfg files."""

from __future__ import annotations

import tomllib
from collections import Counter
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from vassago.configs.models import ValidationIssue
from vassago.configs.models import ValidationLevel
from vassago.configs.paths import MMWAVE_CFG_COMMANDS_PATH
from vassago.configs.paths import resolve_repo_path
from vassago.firmware.mmwave.cfg import CfgCommand
from vassago.firmware.mmwave.cfg import load_cfg_commands

if TYPE_CHECKING:
    from pathlib import Path

    from vassago.configs.models import ConfigMetadata

SUPPORTED_STATUS = "supported"
WARN_STATUS = "warn"
CHANNEL_CFG_RX_MASK_ARG_INDEX = 0
CHANNEL_CFG_TX_MASK_ARG_INDEX = 1
PROFILE_CFG_NUM_ADC_SAMPLES_ARG_INDEX = 9
FRAME_CFG_CHIRP_START_ARG_INDEX = 0
FRAME_CFG_CHIRP_END_ARG_INDEX = 1
FRAME_CFG_LOOP_COUNT_ARG_INDEX = 2
MIN_CHANNEL_CFG_ARGS = CHANNEL_CFG_TX_MASK_ARG_INDEX + 1
MIN_PROFILE_CFG_ARGS = PROFILE_CFG_NUM_ADC_SAMPLES_ARG_INDEX + 1
MIN_FRAME_CFG_ARGS = FRAME_CFG_LOOP_COUNT_ARG_INDEX + 1
MMWAVE_RISK_LEVELS = frozenset({"low", "medium", "high"})


@dataclass(slots=True, frozen=True)
class CommandSpec:
    """One allowed mmWave cfg command loaded from the registry."""

    name: str
    status: str
    arg_counts: tuple[int, ...]
    min_occurs: int
    max_occurs: int | None
    must_be_last: bool
    notes: str | None


@lru_cache
def load_command_registry() -> dict[str, CommandSpec]:
    """Load the allowed mmWave cfg commands from the registry config."""
    registry_path = resolve_repo_path(MMWAVE_CFG_COMMANDS_PATH)
    with registry_path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        msg = f"mmWave cfg command registry must parse to a TOML table: {registry_path}"
        raise TypeError(msg)

    raw_commands = data.get("commands")
    if not isinstance(raw_commands, dict) or not raw_commands:
        msg = (
            "mmWave cfg command registry must define a [commands] table: "
            f"{registry_path}"
        )
        raise ValueError(msg)

    return {
        name: _parse_command_spec(name, raw_spec, registry_path=registry_path)
        for name, raw_spec in raw_commands.items()
    }


def clear_command_registry_cache() -> None:
    """Clear the cached mmWave command registry."""
    load_command_registry.cache_clear()


def validate_cfg(
    path: Path,
    *,
    metadata: ConfigMetadata | None = None,
) -> list[ValidationIssue]:
    """Validate one mmWave cfg file against the shared command registry."""
    issues: list[ValidationIssue] = []
    if metadata is not None:
        issues.extend(_validate_cfg_metadata(metadata))

    commands = load_cfg_commands(path)
    registry = load_command_registry()
    counts: Counter[str] = Counter()
    commands_by_name: dict[str, list[CfgCommand]] = defaultdict(list)

    for index, command in enumerate(commands):
        spec = registry.get(command.name)
        if spec is None:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.ERROR,
                    message=(
                        f"Unknown cfg command {command.name!r} at line "
                        f"{command.line_no}."
                    ),
                )
            )
            continue

        counts[command.name] += 1
        commands_by_name[command.name].append(command)
        issues.extend(_validate_command_shape(command, spec=spec))
        issues.extend(
            _validate_command_status(
                command,
                spec=spec,
                command_index=index,
                commands=commands,
            )
        )

    for spec in registry.values():
        issues.extend(_validate_command_count(spec, count=counts.get(spec.name, 0)))

    issues.extend(_validate_derived_cfg_constraints(commands_by_name))
    return issues


def _parse_command_spec(
    name: str,
    raw_spec: object,
    *,
    registry_path: Path,
) -> CommandSpec:
    """Parse one command registry item."""
    if not isinstance(raw_spec, dict):
        msg = f"Command spec for {name!r} must be a table in {registry_path}"
        raise TypeError(msg)

    status = _require_str(raw_spec, "status", registry_path=registry_path, name=name)
    if status not in {SUPPORTED_STATUS, WARN_STATUS}:
        msg = f"Unsupported status {status!r} for {name!r} in {registry_path}"
        raise ValueError(msg)

    arg_counts = tuple(
        _require_int_list(
            raw_spec,
            "arg_counts",
            registry_path=registry_path,
            name=name,
        )
    )
    required = _optional_bool(raw_spec.get("required"), default=False)
    min_occurs = _optional_int(raw_spec.get("min_occurs"), default=1 if required else 0)
    max_occurs = _optional_int_or_none(raw_spec.get("max_occurs"))
    must_be_last = _optional_bool(raw_spec.get("must_be_last"), default=False)
    notes = _optional_str(raw_spec.get("notes"))

    return CommandSpec(
        name=name,
        status=status,
        arg_counts=arg_counts,
        min_occurs=min_occurs,
        max_occurs=max_occurs,
        must_be_last=must_be_last,
        notes=notes,
    )


def _validate_cfg_metadata(metadata: ConfigMetadata) -> list[ValidationIssue]:
    """Validate header extras required by the managed cfg catalog."""
    issues: list[ValidationIssue] = []
    risk = metadata.extras.get("risk")
    if not isinstance(risk, str) or risk.strip() not in MMWAVE_RISK_LEVELS:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message=(
                    "mmWave cfg metadata must define risk as one of "
                    f"{sorted(MMWAVE_RISK_LEVELS)!r}."
                ),
            )
        )

    recommended_for_bringup = metadata.extras.get("recommended_for_bringup")
    if not isinstance(recommended_for_bringup, bool):
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message=(
                    "mmWave cfg metadata must define recommended_for_bringup as "
                    "a boolean."
                ),
            )
        )
    return issues


def _validate_command_shape(
    command: CfgCommand,
    *,
    spec: CommandSpec,
) -> list[ValidationIssue]:
    """Validate the argument count for one cfg command line."""
    if len(command.args) in spec.arg_counts:
        return []

    return [
        ValidationIssue(
            level=ValidationLevel.ERROR,
            message=(
                f"{command.name} at line {command.line_no} expects arg counts "
                f"{list(spec.arg_counts)!r}, got {len(command.args)}."
            ),
        )
    ]


def _validate_command_status(
    command: CfgCommand,
    *,
    spec: CommandSpec,
    command_index: int,
    commands: list[CfgCommand],
) -> list[ValidationIssue]:
    """Emit warnings and ordering errors for one cfg command line."""
    issues: list[ValidationIssue] = []
    if spec.status == WARN_STATUS:
        note_text = f" {spec.notes}" if spec.notes else ""
        issues.append(
            ValidationIssue(
                level=ValidationLevel.WARN,
                message=(
                    f"{command.name} at line {command.line_no} is allowed but "
                    f"flagged as WARN.{note_text}"
                ),
            )
        )

    if spec.must_be_last and command_index != len(commands) - 1:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message=(
                    f"{command.name} at line {command.line_no} must be the last "
                    "cfg command."
                ),
            )
        )
    return issues


def _validate_command_count(
    spec: CommandSpec,
    *,
    count: int,
) -> list[ValidationIssue]:
    """Validate total occurrence counts for one cfg command type."""
    issues: list[ValidationIssue] = []
    if count < spec.min_occurs:
        qualifier = (
            "must appear"
            if spec.min_occurs == 1
            else f"must appear at least {spec.min_occurs} times"
        )
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message=f"{spec.name} {qualifier}.",
            )
        )

    if spec.max_occurs is not None and count > spec.max_occurs:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message=(
                    f"{spec.name} appears {count} times, which exceeds the "
                    f"maximum of {spec.max_occurs}."
                ),
            )
        )
    return issues


def _validate_derived_cfg_constraints(
    commands_by_name: dict[str, list[CfgCommand]],
) -> list[ValidationIssue]:
    """Run semantic checks that depend on multiple cfg commands."""
    issues: list[ValidationIssue] = []
    tx_antenna_count = _validate_channel_cfg(commands_by_name, issues=issues)
    _validate_profile_cfg(commands_by_name, issues=issues)
    _validate_frame_cfg(
        commands_by_name,
        tx_antenna_count=tx_antenna_count,
        issues=issues,
    )
    return issues


def _validate_channel_cfg(
    commands_by_name: dict[str, list[CfgCommand]],
    *,
    issues: list[ValidationIssue],
) -> int | None:
    """Validate channelCfg masks and return the enabled TX antenna count."""
    command = _first_command(commands_by_name, "channelCfg")
    if command is None or len(command.args) < MIN_CHANNEL_CFG_ARGS:
        return None

    rx_mask = _parse_int_arg(
        command,
        CHANNEL_CFG_RX_MASK_ARG_INDEX,
        field_name="channelCfg.rxMask",
        issues=issues,
    )
    tx_mask = _parse_int_arg(
        command,
        CHANNEL_CFG_TX_MASK_ARG_INDEX,
        field_name="channelCfg.txMask",
        issues=issues,
    )
    if rx_mask is not None and rx_mask <= 0:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message="channelCfg must enable at least one RX antenna.",
            )
        )
    if tx_mask is not None and tx_mask <= 0:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message="channelCfg must enable at least one TX antenna.",
            )
        )
    if tx_mask is None or tx_mask <= 0:
        return None
    return tx_mask.bit_count()


def _validate_profile_cfg(
    commands_by_name: dict[str, list[CfgCommand]],
    *,
    issues: list[ValidationIssue],
) -> None:
    """Validate profileCfg numeric constraints."""
    command = _first_command(commands_by_name, "profileCfg")
    if command is None or len(command.args) < MIN_PROFILE_CFG_ARGS:
        return

    num_adc_samples = _parse_int_arg(
        command,
        PROFILE_CFG_NUM_ADC_SAMPLES_ARG_INDEX,
        field_name="profileCfg.numAdcSamples",
        issues=issues,
    )
    if num_adc_samples is not None and num_adc_samples <= 0:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message="profileCfg numAdcSamples must be positive.",
            )
        )


def _validate_frame_cfg(
    commands_by_name: dict[str, list[CfgCommand]],
    *,
    tx_antenna_count: int | None,
    issues: list[ValidationIssue],
) -> None:
    """Validate frameCfg bounds and TX divisibility constraints."""
    command = _first_command(commands_by_name, "frameCfg")
    if command is None or len(command.args) < MIN_FRAME_CFG_ARGS:
        return

    chirp_start_index = _parse_int_arg(
        command,
        FRAME_CFG_CHIRP_START_ARG_INDEX,
        field_name="frameCfg.chirpStartIndex",
        issues=issues,
    )
    chirp_end_index = _parse_int_arg(
        command,
        FRAME_CFG_CHIRP_END_ARG_INDEX,
        field_name="frameCfg.chirpEndIndex",
        issues=issues,
    )
    loop_count = _parse_int_arg(
        command,
        FRAME_CFG_LOOP_COUNT_ARG_INDEX,
        field_name="frameCfg.loopCount",
        issues=issues,
    )
    if (
        chirp_start_index is not None
        and chirp_end_index is not None
        and chirp_end_index < chirp_start_index
    ):
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message="frameCfg chirpEndIndex must be >= chirpStartIndex.",
            )
        )
    if loop_count is not None and loop_count <= 0:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message="frameCfg loopCount must be positive.",
            )
        )
    if (
        chirp_start_index is None
        or chirp_end_index is None
        or loop_count is None
        or loop_count <= 0
        or chirp_end_index < chirp_start_index
        or tx_antenna_count is None
        or tx_antenna_count <= 0
    ):
        return

    chirps_per_frame = (chirp_end_index - chirp_start_index + 1) * loop_count
    if chirps_per_frame % tx_antenna_count != 0:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message=(
                    "frameCfg chirp count per frame must be divisible by the "
                    "enabled TX antenna count."
                ),
            )
        )


def _first_command(
    commands_by_name: dict[str, list[CfgCommand]],
    name: str,
) -> CfgCommand | None:
    """Return the first occurrence of one cfg command."""
    commands = commands_by_name.get(name)
    if not commands:
        return None
    return commands[0]


def _parse_int_arg(
    command: CfgCommand,
    arg_index: int,
    *,
    field_name: str,
    issues: list[ValidationIssue],
) -> int | None:
    """Parse one integer cfg argument and emit a validation error on failure."""
    try:
        return int(command.args[arg_index], 0)
    except ValueError:
        issues.append(
            ValidationIssue(
                level=ValidationLevel.ERROR,
                message=(
                    f"{field_name} at line {command.line_no} must be an integer, "
                    f"got {command.args[arg_index]!r}."
                ),
            )
        )
        return None


def _require_str(
    data: dict[str, object],
    key: str,
    *,
    registry_path: Path,
    name: str,
) -> str:
    """Require one non-empty string from the command registry."""
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    msg = f"Command spec {name!r} is missing string field {key!r} in {registry_path}"
    raise ValueError(msg)


def _require_int_list(
    data: dict[str, object],
    key: str,
    *,
    registry_path: Path,
    name: str,
) -> list[int]:
    """Require one integer list from the command registry."""
    value = data.get(key)
    if not isinstance(value, list) or not value:
        msg = (
            f"Command spec {name!r} is missing integer list {key!r} in {registry_path}"
        )
        raise ValueError(msg)

    if not all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        msg = f"Command spec {name!r} field {key!r} must contain integers only."
        raise ValueError(msg)
    return value


def _optional_bool(value: object, *, default: bool) -> bool:
    """Parse one optional boolean from the command registry."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    msg = "Expected a boolean value."
    raise ValueError(msg)


def _optional_int(value: object, *, default: int) -> int:
    """Parse one optional integer from the command registry."""
    if value is None:
        return default
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    msg = "Expected an integer value."
    raise ValueError(msg)


def _optional_int_or_none(value: object) -> int | None:
    """Parse one optional integer-or-null from the command registry."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    msg = "Expected an integer or null value."
    raise ValueError(msg)


def _optional_str(value: object) -> str | None:
    """Parse one optional string from the command registry."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    msg = "Expected a string or null value."
    raise ValueError(msg)
