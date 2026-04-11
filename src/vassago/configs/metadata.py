"""Structured metadata header parsing for managed config files."""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING
from typing import Any

from vassago.configs.models import ConfigKind
from vassago.configs.models import ConfigLifecycle
from vassago.configs.models import ConfigMetadata

if TYPE_CHECKING:
    from pathlib import Path

META_BEGIN_MARKER = "--- vassago:meta ---"
META_END_MARKER = "---"
HEADER_ONLY_KEYS = frozenset(
    {
        "config_kind",
        "config_id",
        "label",
        "description",
        "lifecycle",
    }
)


def parse_metadata_header(path: Path) -> ConfigMetadata:
    """Parse the structured metadata header from one managed config file."""
    resolved_path = path.resolve()
    comment_prefix = _comment_prefix_for(resolved_path)
    raw_metadata = _load_header_block(
        resolved_path,
        comment_prefix=comment_prefix,
    )

    config_kind = ConfigKind(_require_str(raw_metadata, "config_kind"))
    config_id = _require_str(raw_metadata, "config_id")
    label = _require_str(raw_metadata, "label")
    description = _require_str(raw_metadata, "description")
    lifecycle = ConfigLifecycle(_require_str(raw_metadata, "lifecycle"))
    extras = {
        key: value for key, value in raw_metadata.items() if key not in HEADER_ONLY_KEYS
    }
    return ConfigMetadata(
        kind=config_kind,
        config_id=config_id,
        label=label,
        description=description,
        lifecycle=lifecycle,
        extras=extras,
    )


def _comment_prefix_for(path: Path) -> str:
    """Resolve the expected structured-comment prefix from one suffix."""
    if path.suffix == ".cfg":
        return "%"
    if path.suffix == ".toml":
        return "#"

    msg = f"Unsupported managed config suffix: {path.suffix}"
    raise ValueError(msg)


def _load_header_block(
    path: Path,
    *,
    comment_prefix: str,
) -> dict[str, Any]:
    """Load the header block text and parse it as TOML."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        msg = f"Config file is empty: {path}"
        raise ValueError(msg)

    first_line = _strip_comment(lines[0], comment_prefix=comment_prefix)
    if first_line != META_BEGIN_MARKER:
        msg = f"Missing metadata header start marker in {path}"
        raise ValueError(msg)

    header_lines: list[str] = []
    for raw_line in lines[1:]:
        stripped = _strip_comment(raw_line, comment_prefix=comment_prefix)
        if stripped == META_END_MARKER:
            break
        header_lines.append(stripped)
    else:
        msg = f"Missing metadata header end marker in {path}"
        raise ValueError(msg)

    data = tomllib.loads("\n".join(header_lines))
    if not isinstance(data, dict):
        msg = f"Metadata header must parse to a TOML table in {path}"
        raise TypeError(msg)
    return data


def _strip_comment(raw_line: str, *, comment_prefix: str) -> str:
    """Strip one required comment prefix from a metadata header line."""
    if not raw_line.startswith(comment_prefix):
        msg = f"Metadata header line must start with {comment_prefix!r}: {raw_line!r}"
        raise ValueError(msg)

    stripped = raw_line[len(comment_prefix) :]
    stripped = stripped.removeprefix(" ")
    return stripped.rstrip()


def _require_str(data: dict[str, Any], key: str) -> str:
    """Require one non-empty string from parsed header data."""
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()

    msg = f"Missing string metadata field {key!r}"
    raise ValueError(msg)
