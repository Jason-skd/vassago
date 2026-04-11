"""TOML-backed collection profile loading for RD workflows."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vassago.collection.rd.paths import resolve_repo_path
from vassago.collection.rd.paths import to_repo_relative_path

CONFIG_SCHEMA_VERSION = "collection_rd_config_v1"
DEFAULT_BATCH_SIZE = 20
DEFAULT_CAPTURE_DURATION_SECONDS = 5.0
DEFAULT_CLI_BAUDRATE = 115_200
DEFAULT_DATA_BAUDRATE = 921_600
DEFAULT_COLLECTION_CONFIGS_ROOT = Path("configs/collection/rd")


@dataclass(slots=True, frozen=True)
class WindowRange:
    """One relative window inside the fixed 5-second capture."""

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
    operator_name: str
    radar_id: str
    firmware_id: str

    def as_dict(self) -> dict[str, object]:
        """Convert defaults to a JSON-ready mapping."""
        return {
            "hand": self.hand,
            "distance_m": self.distance_m,
            "angle_deg": self.angle_deg,
            "environment": self.environment,
            "operator_name": self.operator_name,
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
class CollectionTargetWindow:
    """One gesture + speed mapping to a target window."""

    gesture: str
    speed: str
    window: WindowRange

    def as_dict(self) -> dict[str, object]:
        """Convert the mapping to a JSON-ready mapping."""
        return {
            "gesture": self.gesture,
            "speed": self.speed,
            **self.window.as_dict(),
        }


@dataclass(slots=True, frozen=True)
class CollectionProfile:
    """One dev-maintained collection profile exposed to the operator."""

    config_id: str
    path: Path
    label: str
    description: str
    capture_duration_s: float
    batch_size: int
    firmware_config_id: str
    firmware_config_path: Path
    defaults: CollectionDefaults
    serial: CollectionSerialDefaults
    gestures: tuple[str, ...]
    speeds: tuple[str, ...]
    environments: tuple[str, ...]
    target_windows: tuple[CollectionTargetWindow, ...]

    def speeds_for_gesture(self, gesture: str) -> tuple[str, ...]:
        """Return the configured speeds supported by one gesture."""
        return tuple(
            target_window.speed
            for target_window in self.target_windows
            if target_window.gesture == gesture
        )

    def target_window_for(self, *, gesture: str, speed: str) -> WindowRange:
        """Resolve the configured target window for one gesture + speed pair."""
        for target_window in self.target_windows:
            if target_window.gesture == gesture and target_window.speed == speed:
                return target_window.window

        msg = (
            "Target window is not defined for "
            f"gesture={gesture!r}, speed={speed!r} in {self.path}"
        )
        raise KeyError(msg)

    def as_snapshot(self) -> dict[str, object]:
        """Build the manifest snapshot for this profile."""
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "config_id": self.config_id,
            "source_path": to_repo_relative_path(self.path),
            "label": self.label,
            "description": self.description,
            "capture_duration_s": self.capture_duration_s,
            "batch_size": self.batch_size,
            "firmware": {
                "config_id": self.firmware_config_id,
                "config_path": to_repo_relative_path(self.firmware_config_path),
            },
            "defaults": self.defaults.as_dict(),
            "serial": self.serial.as_dict(),
            "options": {
                "gestures": list(self.gestures),
                "speeds": list(self.speeds),
                "environments": list(self.environments),
            },
            "target_windows": [
                target_window.as_dict() for target_window in self.target_windows
            ],
        }


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
    with resolved_path.open("rb") as handle:
        data = tomllib.load(handle)

    config_id, label, description, capture_duration_s, batch_size = _load_scalars(
        data,
        resolved_path=resolved_path,
    )
    firmware_config_id, firmware_config_path = _load_firmware_binding(data)
    defaults = _load_defaults(data, resolved_path=resolved_path)
    serial = _load_serial_defaults(data)
    gestures, speeds, environments = _load_options(
        data,
        defaults=defaults,
        resolved_path=resolved_path,
    )
    target_windows = _load_target_windows(
        data,
        gestures=gestures,
        speeds=speeds,
        capture_duration_s=capture_duration_s,
        resolved_path=resolved_path,
    )

    return CollectionProfile(
        config_id=config_id,
        path=resolved_path,
        label=label,
        description=description,
        capture_duration_s=capture_duration_s,
        batch_size=batch_size,
        firmware_config_id=firmware_config_id,
        firmware_config_path=firmware_config_path,
        defaults=defaults,
        serial=serial,
        gestures=gestures,
        speeds=speeds,
        environments=environments,
        target_windows=tuple(target_windows),
    )


def _load_scalars(
    data: dict[str, Any],
    *,
    resolved_path: Path,
) -> tuple[str, str, str, float, int]:
    """Load the top-level scalar fields from one profile."""
    config_id = _require_str(data, "config_id")
    label = _require_str(data, "label")
    description = _require_str(data, "description")
    capture_duration_s = _require_float(
        data,
        "capture_duration_s",
        default=DEFAULT_CAPTURE_DURATION_SECONDS,
    )
    if capture_duration_s != DEFAULT_CAPTURE_DURATION_SECONDS:
        msg = (
            "RD collection currently requires capture_duration_s to be exactly "
            f"{DEFAULT_CAPTURE_DURATION_SECONDS:g}s in {resolved_path}"
        )
        raise ValueError(msg)

    batch_size = _require_int(data, "batch_size", default=DEFAULT_BATCH_SIZE)
    if batch_size <= 0:
        msg = f"batch_size must be positive in {resolved_path}"
        raise ValueError(msg)

    return config_id, label, description, capture_duration_s, batch_size


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
        operator_name=_require_str(defaults_table, "operator_name"),
        radar_id=_require_str(defaults_table, "radar_id"),
        firmware_id=_require_str(defaults_table, "firmware_id"),
    )
    if defaults.hand not in {"left", "right"}:
        msg = f"defaults.hand must be left or right in {resolved_path}"
        raise ValueError(msg)
    return defaults


def _load_serial_defaults(data: dict[str, Any]) -> CollectionSerialDefaults:
    """Load the serial strategy from one profile."""
    serial_table = _require_table(data, "serial")
    return CollectionSerialDefaults(
        cli_port=_optional_str(serial_table.get("cli_port")),
        data_port=_optional_str(serial_table.get("data_port")),
        cli_baudrate=_require_int(
            serial_table,
            "cli_baudrate",
            default=DEFAULT_CLI_BAUDRATE,
        ),
        data_baudrate=_require_int(
            serial_table,
            "data_baudrate",
            default=DEFAULT_DATA_BAUDRATE,
        ),
    )


def _load_options(
    data: dict[str, Any],
    *,
    defaults: CollectionDefaults,
    resolved_path: Path,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Load gestures, speeds, and environments from one profile."""
    options_table = _require_table(data, "options")
    gestures = _require_str_tuple(options_table, "gestures")
    speeds = _require_str_tuple(options_table, "speeds")
    environments = _require_str_tuple(options_table, "environments")

    if defaults.environment not in environments:
        msg = (
            "defaults.environment must be present in options.environments for "
            f"{resolved_path}"
        )
        raise ValueError(msg)

    return gestures, speeds, environments


def _load_target_windows(
    data: dict[str, Any],
    *,
    gestures: tuple[str, ...],
    speeds: tuple[str, ...],
    capture_duration_s: float,
    resolved_path: Path,
) -> list[CollectionTargetWindow]:
    """Load gesture + speed window mappings from one profile."""
    raw_target_windows = data.get("target_windows")
    if not isinstance(raw_target_windows, list) or not raw_target_windows:
        msg = f"target_windows must be a non-empty TOML array in {resolved_path}"
        raise ValueError(msg)

    seen_pairs: set[tuple[str, str]] = set()
    return [
        _parse_target_window(
            item,
            gestures=gestures,
            speeds=speeds,
            capture_duration_s=capture_duration_s,
            seen_pairs=seen_pairs,
            resolved_path=resolved_path,
        )
        for item in raw_target_windows
    ]


def _parse_target_window(
    item: object,
    *,
    gestures: tuple[str, ...],
    speeds: tuple[str, ...],
    capture_duration_s: float,
    seen_pairs: set[tuple[str, str]],
    resolved_path: Path,
) -> CollectionTargetWindow:
    """Parse and validate one target window table."""
    if not isinstance(item, dict):
        msg = f"target_windows entries must be tables in {resolved_path}"
        raise TypeError(msg)

    gesture = _require_str(item, "gesture")
    speed = _require_str(item, "speed")
    if gesture not in gestures:
        msg = f"Unknown gesture {gesture!r} in {resolved_path}"
        raise ValueError(msg)
    if speed not in speeds:
        msg = f"Unknown speed {speed!r} in {resolved_path}"
        raise ValueError(msg)

    pair = (gesture, speed)
    if pair in seen_pairs:
        msg = f"Duplicate target window for {pair!r} in {resolved_path}"
        raise ValueError(msg)
    seen_pairs.add(pair)

    window = WindowRange(
        start_s=_require_float(item, "start_s"),
        end_s=_require_float(item, "end_s"),
    )
    _validate_window(
        window,
        capture_duration_s=capture_duration_s,
        path=resolved_path,
        label=f"target_windows[{gesture}/{speed}]",
    )
    return CollectionTargetWindow(
        gesture=gesture,
        speed=speed,
        window=window,
    )


def _validate_window(
    window: WindowRange,
    *,
    capture_duration_s: float,
    path: Path,
    label: str,
) -> None:
    """Validate one configured window against the fixed capture duration."""
    if window.start_s < 0 or window.end_s > capture_duration_s:
        msg = f"{label} must stay inside 0..{capture_duration_s:g}s in {path}"
        raise ValueError(msg)
    if window.start_s >= window.end_s:
        msg = f"{label} must satisfy start_s < end_s in {path}"
        raise ValueError(msg)


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

    return _optional_float(data[key], allow_none=False)


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
        msg = f"Expected a non-empty list of strings for {key!r}"
        raise ValueError(msg)

    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            msg = f"Expected a non-empty string in {key!r}"
            raise ValueError(msg)
        stripped = item.strip()
        if stripped not in normalized:
            normalized.append(stripped)

    return tuple(normalized)
