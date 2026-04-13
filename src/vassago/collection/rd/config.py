"""Header-backed collection config loading for RD workflows."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from vassago.configs.catalog import ConfigCatalog
from vassago.configs.catalog import load_catalog
from vassago.configs.metadata import HEADER_ONLY_KEYS
from vassago.configs.metadata import parse_metadata_header
from vassago.configs.models import ConfigKind
from vassago.configs.models import ConfigLifecycle
from vassago.configs.paths import resolve_repo_path

if TYPE_CHECKING:
    from vassago.configs.models import ConfigMetadata

CONFIG_SCHEMA_VERSION = "collection_rd_config_v5"
DEFAULT_BATCH_SIZE = 20
DEFAULT_CAPTURE_WINDOW_DURATION_SECONDS = 5.0
DEFAULT_COUNTDOWN_DURATION_SECONDS = 5.0
DEFAULT_MARKED_WINDOW_END_GRACE_SECONDS = 0.25
DEFAULT_END_MARK_KEY = "space"
DEFAULT_CLI_BAUDRATE = 115_200
DEFAULT_DATA_BAUDRATE = 921_600
DEFAULT_COLLECTION_PROFILES_ROOT = Path("configs/collection/rd/profiles")


@dataclass(slots=True, frozen=True)
class WindowRange:
    """One relative window inside a fixed raw capture."""

    start_s: float
    end_s: float

    def as_dict(self) -> dict[str, float]:
        """Convert the window to a JSON-ready mapping."""
        return {
            "start_s": self.start_s,
            "end_s": self.end_s,
        }


@dataclass(slots=True, frozen=True)
class CollectionDefaults:
    """Default operator-facing values carried by one collection profile."""

    hand: str
    distance_m: float | None
    angle_deg: float | None
    environment: str
    radar_id: str
    firmware_id: str
    firmware_config_id: str

    def as_dict(self) -> dict[str, object]:
        """Convert defaults to a JSON-ready mapping."""
        return {
            "hand": self.hand,
            "distance_m": self.distance_m,
            "angle_deg": self.angle_deg,
            "environment": self.environment,
            "radar_id": self.radar_id,
            "firmware_id": self.firmware_id,
            "firmware_config_id": self.firmware_config_id,
        }


@dataclass(slots=True, frozen=True)
class CollectionSerialDefaults:
    """Serial strategy carried by one collection profile."""

    cli_port: str | None
    data_port: str | None
    cli_baudrate: int
    data_baudrate: int

    def as_dict(self) -> dict[str, object]:
        """Convert serial defaults to a JSON-ready mapping."""
        return {
            "cli_port": self.cli_port,
            "data_port": self.data_port,
            "cli_baudrate": self.cli_baudrate,
            "data_baudrate": self.data_baudrate,
        }


@dataclass(slots=True, frozen=True)
class GestureTargetDuration:
    """Configured target-window duration for one gesture."""

    gesture: str
    target_window_duration_s: float

    def as_pair(self) -> tuple[str, float]:
        """Convert the duration mapping to one key/value pair."""
        return self.gesture, self.target_window_duration_s


@dataclass(slots=True, frozen=True)
class CollectionGlobalConfig:
    """Repository baseline for RD collection runtime defaults."""

    config_id: str
    path: Path
    label: str
    description: str
    capture_window_duration_s: float
    countdown_duration_s: float
    marked_window_end_grace_s: float
    end_mark_key: str
    serial: CollectionSerialDefaults


@dataclass(slots=True, frozen=True)
class CollectionProfile:
    """One dev-maintained collection profile exposed to the operator."""

    config_id: str
    path: Path
    label: str
    description: str
    global_config_id: str
    batch_size: int
    defaults: CollectionDefaults
    serial: CollectionSerialDefaults
    gestures: tuple[str, ...]
    environments: tuple[str, ...]
    gesture_target_durations: tuple[GestureTargetDuration, ...]
    capture_window_duration_s: float
    countdown_duration_s: float
    marked_window_end_grace_s: float
    end_mark_key: str

    @property
    def capture_duration_s(self) -> float:
        """Compatibility alias for callers that still say capture_duration."""
        return self.capture_window_duration_s

    @property
    def default_firmware_config_id(self) -> str:
        """Return the default firmware cfg id carried by this profile."""
        return self.defaults.firmware_config_id

    def target_window_duration_for(self, *, gesture: str) -> float:
        """Resolve the configured target-window duration for one gesture."""
        for target_duration in self.gesture_target_durations:
            if target_duration.gesture == gesture:
                return target_duration.target_window_duration_s

        msg = f"Target-window duration is not defined for gesture={gesture!r}."
        raise KeyError(msg)

    def as_snapshot(self) -> dict[str, object]:
        """Build the manifest snapshot for this profile."""
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "config_id": self.config_id,
            "label": self.label,
            "description": self.description,
            "batch_size": self.batch_size,
            "global": {
                "config_id": self.global_config_id,
            },
            "runtime": {
                "capture_window_duration_s": self.capture_window_duration_s,
                "countdown_duration_s": self.countdown_duration_s,
                "marked_window_end_grace_s": self.marked_window_end_grace_s,
                "end_mark_key": self.end_mark_key,
            },
            "defaults": self.defaults.as_dict(),
            "serial": self.serial.as_dict(),
            "options": {
                "gestures": list(self.gestures),
                "environments": list(self.environments),
            },
            "gesture_target_durations": dict(
                item.as_pair() for item in self.gesture_target_durations
            ),
        }


def list_collection_profiles(
    *,
    configs_root: Path = DEFAULT_COLLECTION_PROFILES_ROOT,
    catalog: ConfigCatalog | None = None,
) -> list[CollectionProfile]:
    """Return all active repository-managed collection profiles."""
    if configs_root != DEFAULT_COLLECTION_PROFILES_ROOT:
        profiles_root = resolve_repo_path(configs_root)
        if not profiles_root.exists():
            return []
        return [
            load_collection_profile(path)
            for path in sorted(profiles_root.glob("*.toml"))
        ]

    resolved_catalog = catalog or load_catalog()
    return [
        load_collection_profile(entry.path, catalog=resolved_catalog)
        for entry in resolved_catalog.list_entries(
            kind=ConfigKind.COLLECTION_RD_PROFILE,
            lifecycle=ConfigLifecycle.ACTIVE,
        )
    ]


def get_collection_profile(
    config_id: str,
    *,
    configs_root: Path = DEFAULT_COLLECTION_PROFILES_ROOT,
    catalog: ConfigCatalog | None = None,
) -> CollectionProfile:
    """Resolve one active collection profile by config id."""
    if configs_root != DEFAULT_COLLECTION_PROFILES_ROOT:
        for profile in list_collection_profiles(configs_root=configs_root):
            if profile.config_id == config_id:
                return profile
        msg = f"Unknown collection config id: {config_id}"
        raise KeyError(msg)

    resolved_catalog = catalog or load_catalog()
    entry = resolved_catalog.require_entry(
        kind=ConfigKind.COLLECTION_RD_PROFILE,
        config_id=config_id,
    )
    if entry.lifecycle != ConfigLifecycle.ACTIVE:
        msg = f"Collection profile {config_id!r} is not active."
        raise KeyError(msg)
    return load_collection_profile(entry.path, catalog=resolved_catalog)


def load_collection_profile(
    path: Path,
    *,
    catalog: ConfigCatalog | None = None,
) -> CollectionProfile:
    """Load and validate one RD collection profile from TOML."""
    resolved_path = resolve_repo_path(path)
    resolved_catalog = catalog or load_catalog()
    metadata = _load_required_metadata(
        resolved_path,
        expected_kind=ConfigKind.COLLECTION_RD_PROFILE,
    )
    data = load_raw_toml(resolved_path)
    _reject_header_only_keys(data, resolved_path=resolved_path)

    global_config_id = _load_global_binding(data)
    global_config = load_collection_global_config_by_id(
        global_config_id,
        catalog=resolved_catalog,
    )
    batch_size = _load_batch_size(data, resolved_path=resolved_path)
    defaults = _load_defaults(
        data, resolved_catalog=resolved_catalog, resolved_path=resolved_path
    )
    default_firmware_config_id = defaults.firmware_config_id
    _require_mmwave_config(default_firmware_config_id, catalog=resolved_catalog)
    capture_window_duration_s = _load_capture_window_duration_s(
        data,
        global_config=global_config,
        resolved_path=resolved_path,
    )
    countdown_duration_s = _load_countdown_duration_s(
        data,
        global_config=global_config,
        resolved_path=resolved_path,
    )
    marked_window_end_grace_s = _load_marked_window_end_grace_s(
        data,
        global_config=global_config,
        resolved_path=resolved_path,
    )
    end_mark_key = _load_end_mark_key(
        data,
        global_config=global_config,
        resolved_path=resolved_path,
    )
    serial = _load_serial_defaults(
        profile_data=data,
        global_config=global_config,
    )
    gestures, environments = _load_options(
        data,
        defaults=defaults,
        resolved_path=resolved_path,
    )
    gesture_target_durations = _load_gesture_target_durations(
        data,
        gestures=gestures,
        capture_window_duration_s=capture_window_duration_s,
        countdown_duration_s=countdown_duration_s,
        marked_window_end_grace_s=marked_window_end_grace_s,
        resolved_path=resolved_path,
    )
    return CollectionProfile(
        config_id=metadata.config_id,
        path=resolved_path,
        label=metadata.label,
        description=metadata.description,
        global_config_id=global_config_id,
        batch_size=batch_size,
        defaults=defaults,
        serial=serial,
        gestures=gestures,
        environments=environments,
        gesture_target_durations=gesture_target_durations,
        capture_window_duration_s=capture_window_duration_s,
        countdown_duration_s=countdown_duration_s,
        marked_window_end_grace_s=marked_window_end_grace_s,
        end_mark_key=end_mark_key,
    )


def load_collection_global_config(
    path: Path | None = None,
    *,
    catalog: ConfigCatalog | None = None,
) -> CollectionGlobalConfig:
    """Load the active RD collection global baseline or one explicit file."""
    if path is None:
        resolved_catalog = catalog or load_catalog()
        entry = resolved_catalog.require_single_active(
            kind=ConfigKind.COLLECTION_RD_GLOBAL
        )
        return load_collection_global_config(path=entry.path, catalog=resolved_catalog)

    resolved_path = resolve_repo_path(path)
    metadata = _load_required_metadata(
        resolved_path,
        expected_kind=ConfigKind.COLLECTION_RD_GLOBAL,
    )
    data = load_raw_toml(resolved_path)
    _reject_header_only_keys(data, resolved_path=resolved_path)
    return CollectionGlobalConfig(
        config_id=metadata.config_id,
        path=resolved_path,
        label=metadata.label,
        description=metadata.description,
        capture_window_duration_s=_load_positive_float(
            data,
            "capture_window_duration_s",
            default=DEFAULT_CAPTURE_WINDOW_DURATION_SECONDS,
            resolved_path=resolved_path,
        ),
        countdown_duration_s=_load_positive_float(
            data,
            "countdown_duration_s",
            default=DEFAULT_COUNTDOWN_DURATION_SECONDS,
            resolved_path=resolved_path,
        ),
        marked_window_end_grace_s=_load_non_negative_float(
            data,
            "marked_window_end_grace_s",
            default=DEFAULT_MARKED_WINDOW_END_GRACE_SECONDS,
            resolved_path=resolved_path,
        ),
        end_mark_key=_load_non_empty_str(
            data,
            "end_mark_key",
            default=DEFAULT_END_MARK_KEY,
            resolved_path=resolved_path,
        ),
        serial=_load_global_serial_defaults(
            data,
            resolved_path=resolved_path,
        ),
    )


def load_collection_global_config_by_id(
    config_id: str,
    *,
    catalog: ConfigCatalog | None = None,
) -> CollectionGlobalConfig:
    """Resolve and load one RD collection global baseline by id."""
    resolved_catalog = catalog or load_catalog()
    entry = resolved_catalog.require_entry(
        kind=ConfigKind.COLLECTION_RD_GLOBAL,
        config_id=config_id,
    )
    return load_collection_global_config(path=entry.path, catalog=resolved_catalog)


def load_raw_toml(path: Path) -> dict[str, Any]:
    """Load one TOML file into a dictionary."""
    resolved_path = resolve_repo_path(path)
    with resolved_path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        msg = f"TOML root must be a table: {resolved_path}"
        raise TypeError(msg)
    return data


def _load_required_metadata(
    path: Path,
    *,
    expected_kind: ConfigKind,
) -> ConfigMetadata:
    metadata = parse_metadata_header(path)
    if metadata.kind != expected_kind:
        msg = f"Config kind mismatch for {path}: {metadata.kind.value}"
        raise ValueError(msg)
    return metadata


def _reject_header_only_keys(
    data: dict[str, Any],
    *,
    resolved_path: Path,
) -> None:
    invalid_keys = sorted(key for key in HEADER_ONLY_KEYS if key in data)
    if not invalid_keys:
        return

    msg = (
        "Header-only metadata must not appear in the TOML body for "
        f"{resolved_path}: {invalid_keys!r}"
    )
    raise ValueError(msg)


def _load_global_binding(data: dict[str, Any]) -> str:
    global_table = _require_table(data, "global")
    return _require_str(global_table, "config_id")


def _load_batch_size(
    data: dict[str, Any],
    *,
    resolved_path: Path,
) -> int:
    batch_size = _require_int(data, "batch_size", default=DEFAULT_BATCH_SIZE)
    if batch_size <= 0:
        msg = f"batch_size must be positive in {resolved_path}"
        raise ValueError(msg)
    return batch_size


def _require_mmwave_config(
    config_id: str,
    *,
    catalog: ConfigCatalog | None = None,
) -> None:
    resolved_catalog = catalog or load_catalog()
    resolved_catalog.require_entry(kind=ConfigKind.MMWAVE_CFG, config_id=config_id)


def _load_capture_window_duration_s(
    data: dict[str, Any],
    *,
    global_config: CollectionGlobalConfig,
    resolved_path: Path,
) -> float:
    duration_s = _resolve_float(
        profile_data=data,
        key="capture_window_duration_s",
        default=global_config.capture_window_duration_s,
    )
    if duration_s <= 0:
        msg = f"capture_window_duration_s must be positive in {resolved_path}"
        raise ValueError(msg)
    return duration_s


def _load_countdown_duration_s(
    data: dict[str, Any],
    *,
    global_config: CollectionGlobalConfig,
    resolved_path: Path,
) -> float:
    duration_s = _resolve_float(
        profile_data=data,
        key="countdown_duration_s",
        default=global_config.countdown_duration_s,
    )
    if duration_s <= 0:
        msg = f"countdown_duration_s must be positive in {resolved_path}"
        raise ValueError(msg)
    return duration_s


def _load_marked_window_end_grace_s(
    data: dict[str, Any],
    *,
    global_config: CollectionGlobalConfig,
    resolved_path: Path,
) -> float:
    grace_s = _resolve_float(
        profile_data=data,
        key="marked_window_end_grace_s",
        default=global_config.marked_window_end_grace_s,
    )
    if grace_s < 0:
        msg = f"marked_window_end_grace_s must be >= 0 in {resolved_path}"
        raise ValueError(msg)
    return grace_s


def _load_end_mark_key(
    data: dict[str, Any],
    *,
    global_config: CollectionGlobalConfig,
    resolved_path: Path,
) -> str:
    end_mark_key = _resolve_str(
        profile_data=data,
        key="end_mark_key",
        default=global_config.end_mark_key,
    )
    if not end_mark_key:
        msg = f"end_mark_key must be non-empty in {resolved_path}"
        raise ValueError(msg)
    return end_mark_key


def _load_defaults(
    data: dict[str, Any],
    *,
    resolved_catalog: ConfigCatalog,
    resolved_path: Path,
) -> CollectionDefaults:
    defaults_table = _require_table(data, "defaults")
    default_firmware_config_id = _load_default_firmware_config_id(
        data=data,
        defaults_table=defaults_table,
        resolved_catalog=resolved_catalog,
        resolved_path=resolved_path,
    )
    defaults = CollectionDefaults(
        hand=_require_str(defaults_table, "hand"),
        distance_m=_optional_float(defaults_table.get("distance_m")),
        angle_deg=_optional_float(defaults_table.get("angle_deg")),
        environment=_require_str(defaults_table, "environment"),
        radar_id=_require_str(defaults_table, "radar_id"),
        firmware_id=_require_str(defaults_table, "firmware_id"),
        firmware_config_id=default_firmware_config_id,
    )
    if defaults.hand not in {"left", "right"}:
        msg = f"defaults.hand must be left or right in {resolved_path}"
        raise ValueError(msg)
    return defaults


def _load_default_firmware_config_id(
    *,
    data: dict[str, Any],
    defaults_table: dict[str, Any],
    resolved_catalog: ConfigCatalog,
    resolved_path: Path,
) -> str:
    if "firmware" in data:
        msg = (
            "Profile [firmware] section is no longer supported; use "
            "defaults.firmware_config_id instead."
        )
        raise ValueError(msg)

    raw_defaults_config_id = defaults_table.get("firmware_config_id")
    if isinstance(raw_defaults_config_id, str) and raw_defaults_config_id:
        _require_mmwave_config(raw_defaults_config_id, catalog=resolved_catalog)
        return raw_defaults_config_id

    msg = f"defaults.firmware_config_id must be defined in {resolved_path}"
    raise ValueError(msg)


def _load_global_serial_defaults(
    data: dict[str, Any],
    *,
    resolved_path: Path,
) -> CollectionSerialDefaults:
    serial_table = _optional_table(data.get("serial"))
    if serial_table is None:
        return CollectionSerialDefaults(
            cli_port=None,
            data_port=None,
            cli_baudrate=DEFAULT_CLI_BAUDRATE,
            data_baudrate=DEFAULT_DATA_BAUDRATE,
        )
    return CollectionSerialDefaults(
        cli_port=_optional_str(serial_table.get("cli_port")),
        data_port=_optional_str(serial_table.get("data_port")),
        cli_baudrate=_load_positive_int_from_table(
            serial_table,
            "cli_baudrate",
            default=DEFAULT_CLI_BAUDRATE,
            resolved_path=resolved_path,
        ),
        data_baudrate=_load_positive_int_from_table(
            serial_table,
            "data_baudrate",
            default=DEFAULT_DATA_BAUDRATE,
            resolved_path=resolved_path,
        ),
    )


def _load_serial_defaults(
    *,
    profile_data: dict[str, Any],
    global_config: CollectionGlobalConfig,
) -> CollectionSerialDefaults:
    profile_serial = _optional_table(profile_data.get("serial"))
    return CollectionSerialDefaults(
        cli_port=_resolve_optional_str_from_table(
            profile_table=profile_serial,
            key="cli_port",
            default=global_config.serial.cli_port,
        ),
        data_port=_resolve_optional_str_from_table(
            profile_table=profile_serial,
            key="data_port",
            default=global_config.serial.data_port,
        ),
        cli_baudrate=_resolve_positive_int_from_table(
            profile_table=profile_serial,
            key="cli_baudrate",
            default=global_config.serial.cli_baudrate,
        ),
        data_baudrate=_resolve_positive_int_from_table(
            profile_table=profile_serial,
            key="data_baudrate",
            default=global_config.serial.data_baudrate,
        ),
    )


def _load_options(
    data: dict[str, Any],
    *,
    defaults: CollectionDefaults,
    resolved_path: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    options_table = _require_table(data, "options")
    gestures = _require_unique_str_tuple(options_table, "gestures")
    environments = _require_unique_str_tuple(options_table, "environments")
    if defaults.environment not in environments:
        msg = (
            "defaults.environment must be present in options.environments for "
            f"{resolved_path}"
        )
        raise ValueError(msg)
    return gestures, environments


def _load_gesture_target_durations(
    data: dict[str, Any],
    *,
    gestures: tuple[str, ...],
    capture_window_duration_s: float,
    countdown_duration_s: float,
    marked_window_end_grace_s: float,
    resolved_path: Path,
) -> tuple[GestureTargetDuration, ...]:
    durations_table = _require_table(data, "gesture_target_durations")
    unexpected_gestures = sorted(key for key in durations_table if key not in gestures)
    if unexpected_gestures:
        msg = (
            "gesture_target_durations contains unknown gestures "
            f"{unexpected_gestures!r} in {resolved_path}"
        )
        raise ValueError(msg)

    target_durations: list[GestureTargetDuration] = []
    for gesture in gestures:
        target_duration_s = _require_float(durations_table, gesture)
        _validate_target_window_duration(
            gesture=gesture,
            target_window_duration_s=target_duration_s,
            capture_window_duration_s=capture_window_duration_s,
            countdown_duration_s=countdown_duration_s,
            marked_window_end_grace_s=marked_window_end_grace_s,
            resolved_path=resolved_path,
        )
        target_durations.append(
            GestureTargetDuration(
                gesture=gesture,
                target_window_duration_s=target_duration_s,
            )
        )
    return tuple(target_durations)


def _validate_target_window_duration(
    *,
    gesture: str,
    target_window_duration_s: float,
    capture_window_duration_s: float,
    countdown_duration_s: float,
    marked_window_end_grace_s: float,
    resolved_path: Path,
) -> None:
    if target_window_duration_s <= 0:
        msg = (
            "gesture_target_durations values must be positive for "
            f"{gesture!r} in {resolved_path}"
        )
        raise ValueError(msg)

    latest_target_end_s = target_window_duration_s + marked_window_end_grace_s
    if latest_target_end_s > capture_window_duration_s:
        msg = (
            "gesture_target_durations values must leave room for grace inside the "
            f"capture window for {gesture!r} in {resolved_path}"
        )
        raise ValueError(msg)

    max_target_start_s = capture_window_duration_s - latest_target_end_s
    if countdown_duration_s < max_target_start_s:
        msg = (
            "countdown_duration_s is too short to randomly place capture_window "
            f"for {gesture!r} in {resolved_path}"
        )
        raise ValueError(msg)


def _load_positive_float(
    data: dict[str, Any],
    key: str,
    *,
    default: float,
    resolved_path: Path,
) -> float:
    value = _require_float(data, key, default=default)
    if value <= 0:
        msg = f"{key} must be positive in {resolved_path}"
        raise ValueError(msg)
    return value


def _load_non_negative_float(
    data: dict[str, Any],
    key: str,
    *,
    default: float,
    resolved_path: Path,
) -> float:
    value = _require_float(data, key, default=default)
    if value < 0:
        msg = f"{key} must be >= 0 in {resolved_path}"
        raise ValueError(msg)
    return value


def _load_non_empty_str(
    data: dict[str, Any],
    key: str,
    *,
    default: str,
    resolved_path: Path,
) -> str:
    value = _require_str(data, key) if key in data else default
    if not value:
        msg = f"{key} must be non-empty in {resolved_path}"
        raise ValueError(msg)
    return value


def _load_positive_int_from_table(
    data: dict[str, Any],
    key: str,
    *,
    default: int,
    resolved_path: Path,
) -> int:
    value = _require_int(data, key, default=default)
    if value <= 0:
        msg = f"{key} must be positive in {resolved_path}"
        raise ValueError(msg)
    return value


def _optional_table(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    msg = "Expected table or null."
    raise ValueError(msg)


def _resolve_float(
    *,
    profile_data: dict[str, Any],
    key: str,
    default: float,
) -> float:
    if key in profile_data:
        return _require_float(profile_data, key)
    return default


def _resolve_str(
    *,
    profile_data: dict[str, Any],
    key: str,
    default: str,
) -> str:
    if key in profile_data:
        return _require_str(profile_data, key)
    return default


def _resolve_optional_str_from_table(
    *,
    profile_table: dict[str, Any] | None,
    key: str,
    default: str | None,
) -> str | None:
    if profile_table is None or key not in profile_table:
        return default
    return _optional_str(profile_table[key])


def _resolve_positive_int_from_table(
    *,
    profile_table: dict[str, Any] | None,
    key: str,
    default: int,
) -> int:
    if profile_table is None or key not in profile_table:
        return default
    value = _require_int(profile_table, key)
    if value <= 0:
        msg = f"{key} must be positive."
        raise ValueError(msg)
    return value


def _require_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if isinstance(value, dict):
        return value
    msg = f"Missing table {key!r}"
    raise ValueError(msg)


def _require_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    msg = f"Missing string field {key!r}"
    raise ValueError(msg)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    msg = "Expected string or null."
    raise ValueError(msg)


def _require_float(
    data: dict[str, Any],
    key: str,
    *,
    default: float | None = None,
) -> float:
    if key not in data:
        if default is None:
            msg = f"Missing numeric field {key!r}"
            raise ValueError(msg)
        return default
    value = _optional_float(data[key], allow_none=False)
    if value is None:
        msg = f"Missing numeric field {key!r}"
        raise ValueError(msg)
    return value


def _optional_float(
    value: object,
    *,
    allow_none: bool = True,
) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, int | float):
        return float(value)
    msg = "Expected a numeric value."
    raise ValueError(msg)


def _require_int(
    data: dict[str, Any],
    key: str,
    *,
    default: int | None = None,
) -> int:
    if key not in data:
        if default is None:
            msg = f"Missing integer field {key!r}"
            raise ValueError(msg)
        return default
    value = data[key]
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    msg = f"Expected integer field {key!r}"
    raise ValueError(msg)


def _require_unique_str_tuple(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        msg = f"Expected a non-empty list of strings for {key!r}"
        raise ValueError(msg)

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            msg = f"Expected non-empty strings in {key!r}"
            raise ValueError(msg)
        normalized_item = item.strip()
        if normalized_item in seen:
            msg = f"Duplicate value {normalized_item!r} in {key!r}"
            raise ValueError(msg)
        seen.add(normalized_item)
        normalized.append(normalized_item)
    return tuple(normalized)
