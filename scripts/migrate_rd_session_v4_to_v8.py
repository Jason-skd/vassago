"""One-off migration for legacy RD gesture session manifests.

This script upgrades top-level session manifests from
`collection_rd_session_v4` to the current v8 contract with the smallest
possible set of changes needed for current QC.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

from vassago.collection.rd import config as collection_config
from vassago.collection.rd import session as collection_session
from vassago.collection.rd.paths import resolve_repo_path

LEGACY_SESSION_SCHEMA_VERSION = "collection_rd_session_v4"

type JsonObject = dict[str, object]


def main() -> int:
    args = _parse_args()
    manifest_paths = _resolve_manifest_paths(args)
    if not manifest_paths:
        print("No manifest.json files matched the requested scope.", file=sys.stderr)
        return 1

    migrated_count = 0
    skipped_count = 0
    failed_count = 0

    for manifest_path in manifest_paths:
        try:
            raw_manifest = _load_manifest_json(manifest_path)
            if raw_manifest.get("schema_version") != LEGACY_SESSION_SCHEMA_VERSION:
                skipped_count += 1
                print(
                    f"SKIP {manifest_path}: "
                    f"schema_version={raw_manifest.get('schema_version')!r}"
                )
                continue

            migrated_manifest = migrate_manifest_v4_to_v8(raw_manifest)
            if args.write:
                backup_path = manifest_path.with_name(
                    manifest_path.stem + args.backup_suffix
                )
                if backup_path.exists():
                    msg = f"backup path already exists: {backup_path}"
                    raise FileExistsError(msg)
                backup_path.write_text(
                    json.dumps(raw_manifest, indent=2, sort_keys=False) + "\n",
                    encoding="utf-8",
                )
                collection_session.write_manifest(
                    manifest_path=manifest_path,
                    manifest=migrated_manifest,
                )
                print(
                    f"WRITE {manifest_path}: {LEGACY_SESSION_SCHEMA_VERSION} -> "
                    f"{migrated_manifest['schema_version']}"
                )
            else:
                print(
                    f"DRY  {manifest_path}: {LEGACY_SESSION_SCHEMA_VERSION} -> "
                    f"{migrated_manifest['schema_version']}"
                )
            migrated_count += 1
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            print(f"FAIL {manifest_path}: {exc}", file=sys.stderr)

    print(
        "\nSummary\n"
        f"checked: {len(manifest_paths)}\n"
        f"migrated: {migrated_count}\n"
        f"skipped: {skipped_count}\n"
        f"failed: {failed_count}\n"
        f"mode: {'write' if args.write else 'dry-run'}"
    )
    return 1 if failed_count else 0


def migrate_manifest_v4_to_v8(manifest: JsonObject) -> JsonObject:
    collection_type = manifest.get(
        "collection_type",
        collection_session.COLLECTION_TYPE_GESTURE,
    )
    if collection_type != collection_session.COLLECTION_TYPE_GESTURE:
        msg = (
            "This one-off script only supports gesture manifests; "
            f"got collection_type={collection_type!r}."
        )
        raise ValueError(msg)

    raw_snapshot = _require_object(manifest, "config_snapshot")
    profile = _load_profile(manifest=manifest, raw_snapshot=raw_snapshot)
    firmware_config_id = _infer_firmware_config_id(
        manifest=manifest,
        raw_snapshot=raw_snapshot,
        profile=profile,
    )
    companion_profile_id = _infer_companion_profile_id(
        raw_snapshot=raw_snapshot,
        profile=profile,
    )

    migrated_snapshot = deepcopy(raw_snapshot)
    migrated_snapshot.setdefault(
        "default_companion_profile_id",
        companion_profile_id,
    )
    snapshot_defaults = _require_object(migrated_snapshot, "defaults")
    snapshot_defaults.setdefault("firmware_config_id", firmware_config_id)

    return {
        "schema_version": collection_session.SESSION_SCHEMA_VERSION,
        "session_id": _require_non_empty_str(manifest, "session_id"),
        "created_at": _require_non_empty_str(manifest, "created_at"),
        "updated_at": _require_non_empty_str(manifest, "updated_at"),
        "session_status": _require_non_empty_str(manifest, "session_status"),
        "collection_type": collection_session.COLLECTION_TYPE_GESTURE,
        "subject_name": _require_non_empty_str(manifest, "subject_name"),
        "hand": _require_non_empty_str(manifest, "hand"),
        "distance_m": manifest.get("distance_m"),
        "angle_deg": manifest.get("angle_deg"),
        "environment": _require_non_empty_str(manifest, "environment"),
        "operator_name": _require_non_empty_str(manifest, "operator_name"),
        "note": manifest.get("note"),
        "radar_id": _require_non_empty_str(manifest, "radar_id"),
        "firmware_id": _require_non_empty_str(manifest, "firmware_id"),
        "firmware_config_id": firmware_config_id,
        "companion_profile_id": companion_profile_id,
        "background_plan": None,
        "background_capture": None,
        "gesture": _require_non_empty_str(manifest, "gesture"),
        "gesture_options": _require_list_copy(manifest, "gesture_options"),
        "environment_options": _require_list_copy(manifest, "environment_options"),
        "cli_port": _require_non_empty_str(manifest, "cli_port"),
        "data_port": _require_non_empty_str(manifest, "data_port"),
        "data_baudrate": _require_int(manifest, "data_baudrate"),
        "config_snapshot": migrated_snapshot,
        "takes": _require_list_copy(manifest, "takes"),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate legacy RD gesture session manifests from "
            "collection_rd_session_v4 to the current v8 contract."
        )
    )
    parser.add_argument(
        "--manifest",
        action="append",
        default=[],
        help="Specific manifest.json path to migrate. Repeatable.",
    )
    parser.add_argument(
        "--sessions-root",
        default=str(collection_session.DEFAULT_SESSIONS_ROOT),
        help=(
            "Sessions root scanned for */manifest.json when --manifest is not used. "
            f"Default: {collection_session.DEFAULT_SESSIONS_ROOT}"
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write migrated manifests in place. Default is dry-run.",
    )
    parser.add_argument(
        "--backup-suffix",
        default=".v4.backup.json",
        help=(
            "Backup filename suffix created next to each manifest in write mode. "
            "Default: .v4.backup.json"
        ),
    )
    return parser.parse_args()


def _resolve_manifest_paths(args: argparse.Namespace) -> tuple[Path, ...]:
    if args.manifest:
        return tuple(resolve_repo_path(Path(path)) for path in args.manifest)

    sessions_root = resolve_repo_path(Path(args.sessions_root))
    if not sessions_root.exists():
        return ()
    return tuple(
        sorted(sessions_root.glob(f"*/{collection_session.MANIFEST_FILENAME}"))
    )


def _load_manifest_json(manifest_path: Path) -> JsonObject:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"Manifest root must be a JSON object: {manifest_path}"
        raise TypeError(msg)
    return data


def _load_profile(
    *,
    manifest: JsonObject,
    raw_snapshot: JsonObject,
) -> collection_config.CollectionProfile:
    raw_profile_id = manifest.get("config_id")
    if not isinstance(raw_profile_id, str) or not raw_profile_id:
        raw_profile_id = raw_snapshot.get("config_id")
    if not isinstance(raw_profile_id, str) or not raw_profile_id:
        msg = (
            "Unable to infer collection profile id from legacy manifest. "
            "Expected top-level config_id or config_snapshot.config_id."
        )
        raise ValueError(msg)
    return collection_config.get_collection_profile(raw_profile_id)


def _infer_firmware_config_id(
    *,
    manifest: JsonObject,
    raw_snapshot: JsonObject,
    profile: collection_config.CollectionProfile,
) -> str:
    raw_firmware_config_id = manifest.get("firmware_config_id")
    if isinstance(raw_firmware_config_id, str) and raw_firmware_config_id:
        return raw_firmware_config_id

    raw_defaults = raw_snapshot.get("defaults")
    if isinstance(raw_defaults, dict):
        defaults_firmware_config_id = raw_defaults.get("firmware_config_id")
        if isinstance(defaults_firmware_config_id, str) and defaults_firmware_config_id:
            return defaults_firmware_config_id

    raw_firmware = raw_snapshot.get("firmware")
    if isinstance(raw_firmware, dict):
        snapshot_firmware_config_id = raw_firmware.get("config_id")
        if isinstance(snapshot_firmware_config_id, str) and snapshot_firmware_config_id:
            return snapshot_firmware_config_id

    return profile.default_firmware_config_id


def _infer_companion_profile_id(
    *,
    raw_snapshot: JsonObject,
    profile: collection_config.CollectionProfile,
) -> str:
    raw_companion_profile_id = raw_snapshot.get("default_companion_profile_id")
    if isinstance(raw_companion_profile_id, str) and raw_companion_profile_id:
        return raw_companion_profile_id
    return profile.default_companion_profile_id


def _require_object(data: JsonObject, key: str) -> JsonObject:
    value = data.get(key)
    if isinstance(value, dict):
        return value
    msg = f"Manifest field {key!r} must be an object."
    raise ValueError(msg)


def _require_non_empty_str(data: JsonObject, key: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value:
        return value
    msg = f"Manifest field {key!r} must be a non-empty string."
    raise ValueError(msg)


def _require_list_copy(data: JsonObject, key: str) -> list[object]:
    value = data.get(key)
    if isinstance(value, list):
        return deepcopy(value)
    msg = f"Manifest field {key!r} must be a list."
    raise ValueError(msg)


def _require_int(data: JsonObject, key: str) -> int:
    value = data.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    msg = f"Manifest field {key!r} must be an integer."
    raise ValueError(msg)


if __name__ == "__main__":
    raise SystemExit(main())
