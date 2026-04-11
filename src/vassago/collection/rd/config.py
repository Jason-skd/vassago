"""TOML-backed collection profile loading for RD workflows."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vassago.collection.rd.paths import resolve_repo_path
from vassago.collection.rd.paths import to_repo_relative_path

CONFIG_SCHEMA_VERSION = "collection_rd_config_v2"
DEFAULT_BATCH_SIZE = 20
DEFAULT_CAPTURE_WINDOW_DURATION_SECONDS = 5.0
DEFAULT_COUNTDOWN_DURATION_SECONDS = 5.0
DEFAULT_MARKED_WINDOW_END_GRACE_SECONDS = 0.25
DEFAULT_END_MARK_KEY = "space"
DEFAULT_CLI_BAUDRATE = 115_200
DEFAULT_DATA_BAUDRATE = 921_600
DEFAULT_COLLECTION_CONFIGS_ROOT = Path("configs/collection/rd")
DEFAULT_GLOBAL_CONFIG_PATH = Path("rd.toml")


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

    def as_dict(self) -> dict[str, object]:
        """Convert defaults to a JSON-ready mapping."""
        return {
            "hand": self.hand,
            "distance_m": self.distance_m,
            "angle_deg": self.angle_deg,
            "environment": self.environment,
            "radar_id": self.radar_id,
            "firmware_id": self.firmware_id,
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
class CollectionProfile:
    """One dev-maintained collection profile exposed to the operator."""

    config_id: str
    path: Path
    label: str
    description: str
    batch_size: int
    firmware_config_id: str
    firmware_config_path: Path
    defaults: CollectionDefaults
    serial: CollectionSerialDefaults
    gestures: tuple[str, ...]
    environments: tuple[str, ...]
    gesture_target_durations: tuple[GestureTargetDuration, ...]
    capture_window_duration_s: float
    countdown_duration_s: float
    marked_window_end_grace_s: float
    end_mark_key: str
    global_path: Path | None = None

    @property
    def capture_duration_s(self) -> float:
        """Compatibility alias for callers that still say capture_duration."""
        return self.capture_window_duration_s

    def target_window_duration_for(self, *, gesture: str) -> float:
        """Resolve the configured target-window duration for one gesture."""
        for target_duration in self.gesture_target_durations:
            if target_duration.gesture == gesture:
                return target_duration.target_window_duration_s

        msg = f"Target-window duration is not defined for gesture={gesture!r}."
        raise KeyError(msg)

    def as_snapshot(self) -> dict[str, object]:
        """Build the manifest snapshot for this profile."""
        snapshot: dict[str, object] = {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "config_id": self.config_id,
            "source_path": to_repo_relative_path(self.path),
            "label": self.label,
            "description": self.description,
            "batch_size": self.batch_size,
            "runtime": {
                "capture_window_duration_s": self.capture_window_duration_s,
                "countdown_duration_s": self.countdown_duration_s,
                "marked_window_end_grace_s": self.marked_window_end_grace_s,
                "end_mark_key": self.end_mark_key,
            },
            "firmware": {
                "config_id": self.firmware_config_id,
                "config_path": to_repo_relative_path(self.firmware_config_path),
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
        if self.global_path is not None:
            snapshot["global_source_path"] = to_repo_relative_path(self.global_path)
        return snapshot


def list_collection_profiles(
    *,
    configs_root: Path = DEFAULT_COLLECTION_CONFIGS_ROOT,
) -> list[CollectionProfile]:
    """Return all repository-managed collection profiles."""
    profiles_root = resolve_repo_path(configs_root)
    if not profiles_root.exists():
        return []

    return [
        load_collection_profile(path) for path in sorted(profiles_root.glob("*.toml"))
    ]


def get_collection_profile(
    config_id: str,
    *,
    configs_root: Path = DEFAULT_COLLECTION_CONFIGS_ROOT,
) -> CollectionProfile:
    """Resolve one profile id from the managed collection profiles."""
    for profile in list_collection_profiles(configs_root=configs_root):
        if profile.config_id == config_id:
            return profile

    msg = f"Unknown collection config id: {config_id}"
    raise KeyError(msg)


def load_collection_profile(path: Path) -> CollectionProfile:
    """Load and validate one RD collection profile from TOML."""
    resolved_path = resolve_repo_path(path)
    data = _load_toml_file(resolved_path)
    global_path, global_data = _load_global_data()

    config_id, label, description, batch_size = _load_scalars(
        data,
        resolved_path=resolved_path,
    )
    firmware_config_id, firmware_config_path = _load_firmware_binding(data)
    capture_window_duration_s = _load_capture_window_duration_s(
        data,
        global_data=global_data,
        resolved_path=resolved_path,
    )
    countdown_duration_s = _load_countdown_duration_s(
        data,
        global_data=global_data,
        resolved_path=resolved_path,
    )
    marked_window_end_grace_s = _load_marked_window_end_grace_s(
        data,
        global_data=global_data,
        resolved_path=resolved_path,
    )
    end_mark_key = _load_end_mark_key(
        data,
        global_data=global_data,
        resolved_path=resolved_path,
    )
    defaults = _load_defaults(data, resolved_path=resolved_path)
    serial = _load_serial_defaults(
        profile_data=data,
        global_data=global_data,
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
        config_id=config_id,
        path=resolved_path,
        label=label,
        description=description,
        batch_size=batch_size,
        firmware_config_id=firmware_config_id,
        firmware_config_path=firmware_config_path,
        defaults=defaults,
        serial=serial,
        gestures=gestures,
        environments=environments,
        gesture_target_durations=gesture_target_durations,
        capture_window_duration_s=capture_window_duration_s,
        countdown_duration_s=countdown_duration_s,
        marked_window_end_grace_s=marked_window_end_grace_s,
        end_mark_key=end_mark_key,
        global_path=global_path,
    )


def _load_toml_file(path: Path) -> dict[str, Any]:
    """Load one TOML file into a dictionary."""
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        msg = f"TOML root must be a table: {path}"
        raise TypeError(msg)
    return data


def _load_global_data() -> tuple[Path | None, dict[str, Any]]:
    """Load the repository-level RD baseline when available."""
    resolved_path = resolve_repo_path(DEFAULT_GLOBAL_CONFIG_PATH)
    if not resolved_path.exists():
        return None, {}
    return resolved_path, _load_toml_file(resolved_path)


def _load_scalars(
    data: dict[str, Any],
    *,
    resolved_path: Path,
) -> tuple[str, str, str, int]:
    """Load the top-level scalar fields from one profile."""
    config_id = _require_str(data, "config_id")
    label = _require_str(data, "label")
    description = _require_str(data, "description")
    batch_size = _require_int(data, "batch_size", default=DEFAULT_BATCH_SIZE)
    if batch_size <= 0:
        msg = f"batch_size must be positive in {resolved_path}"
        raise ValueError(msg)
    return config_id, label, description, batch_size


def _load_capture_window_duration_s(
    data: dict[str, Any],
    *,
    global_data: dict[str, Any],
    resolved_path: Path,
) -> float:
    """Load capture-window duration from profile, global config, or default."""
    duration_s = _resolve_float(
        profile_data=data,
        global_data=global_data,
        key="capture_window_duration_s",
        default=DEFAULT_CAPTURE_WINDOW_DURATION_SECONDS,
    )
    if duration_s <= 0:
        msg = f"capture_window_duration_s must be positive in {resolved_path}"
        raise ValueError(msg)
    return duration_s


def _load_countdown_duration_s(
    data: dict[str, Any],
    *,
    global_data: dict[str, Any],
    resolved_path: Path,
) -> float:
    """Load countdown duration from profile, global config, or default."""
    duration_s = _resolve_float(
        profile_data=data,
        global_data=global_data,
        key="countdown_duration_s",
        default=DEFAULT_COUNTDOWN_DURATION_SECONDS,
    )
    if duration_s <= 0:
        msg = f"countdown_duration_s must be positive in {resolved_path}"
        raise ValueError(msg)
    return duration_s


def _load_marked_window_end_grace_s(
    data: dict[str, Any],
    *,
    global_data: dict[str, Any],
    resolved_path: Path,
) -> float:
    """Load marked-window grace from profile, global config, or default."""
    grace_s = _resolve_float(
        profile_data=data,
        global_data=global_data,
        key="marked_window_end_grace_s",
        default=DEFAULT_MARKED_WINDOW_END_GRACE_SECONDS,
    )
    if grace_s < 0:
        msg = f"marked_window_end_grace_s must be >= 0 in {resolved_path}"
        raise ValueError(msg)
    return grace_s


def _load_end_mark_key(
    data: dict[str, Any],
    *,
    global_data: dict[str, Any],
    resolved_path: Path,
) -> str:
    """Load the configured capture end-mark key."""
    end_mark_key = _resolve_str(
        profile_data=data,
        global_data=global_data,
        key="end_mark_key",
        default=DEFAULT_END_MARK_KEY,
    )
    if not end_mark_key:
        msg = f"end_mark_key must be non-empty in {resolved_path}"
        raise ValueError(msg)
    return end_mark_key


def _load_firmware_binding(
    data: dict[str, Any],
) -> tuple[str, Path]:
    """Load the bound mmWave cfg metadata from one profile."""
    firmware_table = _require_table(data, "firmware")
    firmware_config_id = _require_str(firmware_table, "config_id")
    firmware_config_path = resolve_repo_path(
        _require_str(firmware_table, "config_path"),
    )
    return firmware_config_id, firmware_config_path


def _load_defaults(
    data: dict[str, Any],
    *,
    resolved_path: Path,
) -> CollectionDefaults:
    """Load the operator-facing default values from one profile."""
    defaults_table = _require_table(data, "defaults")
    defaults = CollectionDefaults(
        hand=_require_str(defaults_table, "hand"),
        distance_m=_optional_float(defaults_table.get("distance_m")),
        angle_deg=_optional_float(defaults_table.get("angle_deg")),
        environment=_require_str(defaults_table, "environment"),
        radar_id=_require_str(defaults_table, "radar_id"),
        firmware_id=_require_str(defaults_table, "firmware_id"),
    )
    if defaults.hand not in {"left", "right"}:
        msg = f"defaults.hand must be left or right in {resolved_path}"
        raise ValueError(msg)
    return defaults


def _load_serial_defaults(
    *,
    profile_data: dict[str, Any],
    global_data: dict[str, Any],
) -> CollectionSerialDefaults:
    """Load the serial strategy from the merged global/profile view."""
    profile_serial = _optional_table(profile_data.get("serial"))
    global_serial = _optional_table(global_data.get("serial"))
    return CollectionSerialDefaults(
        cli_port=_resolve_optional_str_from_tables(
            profile_table=profile_serial,
            global_table=global_serial,
            key="cli_port",
        ),
        data_port=_resolve_optional_str_from_tables(
            profile_table=profile_serial,
            global_table=global_serial,
            key="data_port",
        ),
        cli_baudrate=_resolve_int_from_tables(
            profile_table=profile_serial,
            global_table=global_serial,
            key="cli_baudrate",
            default=DEFAULT_CLI_BAUDRATE,
        ),
        data_baudrate=_resolve_int_from_tables(
            profile_table=profile_serial,
            global_table=global_serial,
            key="data_baudrate",
            default=DEFAULT_DATA_BAUDRATE,
        ),
    )


def _load_options(
    data: dict[str, Any],
    *,
    defaults: CollectionDefaults,
    resolved_path: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Load gestures and environments from one profile."""
    options_table = _require_table(data, "options")
    gestures = _require_str_tuple(options_table, "gestures")
    environments = _require_str_tuple(options_table, "environments")

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
    """Load gesture -> target-window duration mappings from one profile."""
    durations_table = _require_table(data, "gesture_target_durations")
    unexpected_gestures = sorted(
        key for key in durations_table if key not in set(gestures)
    )
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
            ),
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
    """Validate one target-window duration against the runtime geometry."""
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


def _optional_table(value: object) -> dict[str, Any] | None:
    """Normalize one optional TOML table."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value

    msg = "Expected table or null."
    raise ValueError(msg)


def _resolve_float(
    *,
    profile_data: dict[str, Any],
    global_data: dict[str, Any],
    key: str,
    default: float,
) -> float:
    """Resolve one numeric value from profile, global config, or default."""
    if key in profile_data:
        return _require_float(profile_data, key)
    if key in global_data:
        return _require_float(global_data, key)
    return default


def _resolve_str(
    *,
    profile_data: dict[str, Any],
    global_data: dict[str, Any],
    key: str,
    default: str,
) -> str:
    """Resolve one string value from profile, global config, or default."""
    if key in profile_data:
        return _require_str(profile_data, key)
    if key in global_data:
        return _require_str(global_data, key)
    return default


def _resolve_optional_str_from_tables(
    *,
    profile_table: dict[str, Any] | None,
    global_table: dict[str, Any] | None,
    key: str,
) -> str | None:
    """Resolve one optional string from merged table sources."""
    if profile_table is not None and key in profile_table:
        return _optional_str(profile_table[key])
    if global_table is not None and key in global_table:
        return _optional_str(global_table[key])
    return None


def _resolve_int_from_tables(
    *,
    profile_table: dict[str, Any] | None,
    global_table: dict[str, Any] | None,
    key: str,
    default: int,
) -> int:
    """Resolve one integer from merged table sources."""
    if profile_table is not None and key in profile_table:
        return _require_int(profile_table, key)
    if global_table is not None and key in global_table:
        return _require_int(global_table, key)
    return default


def _require_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    """Require one TOML table by key."""
    value = data.get(key)
    if isinstance(value, dict):
        return value

    msg = f"Missing table {key!r}"
    raise ValueError(msg)


def _require_str(data: dict[str, Any], key: str) -> str:
    """Require one non-empty string by key."""
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()

    msg = f"Missing string field {key!r}"
    raise ValueError(msg)


def _optional_str(value: object) -> str | None:
    """Normalize one optional string value."""
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
    """Require one numeric field by key."""
    if key not in data:
        if default is None:
            msg = f"Missing numeric field {key!r}"
            raise ValueError(msg)
        return default

    value = _optional_float(data[key], allow_none=False)
    if value is None:
        msg = f"Field {key!r} must be numeric."
        raise ValueError(msg)
    return value


def _optional_float(
    value: object,
    *,
    allow_none: bool = True,
) -> float | None:
    """Normalize one optional float value."""
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
    """Require one integer field by key."""
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


def _require_str_tuple(data: dict[str, Any], key: str) -> tuple[str, ...]:
    """Require one non-empty string list by key."""
    value = data.get(key)
    if not isinstance(value, list) or not value:
        msg = f"Expected a non-empty string list for {key!r}"
        raise ValueError(msg)

    items = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            msg = f"Expected only non-empty strings in {key!r}"
            raise ValueError(msg)
        items.append(item.strip())

    deduped_items = tuple(dict.fromkeys(items))
    if len(deduped_items) != len(items):
        msg = f"Duplicate values are not allowed in {key!r}"
        raise ValueError(msg)
    return deduped_items
