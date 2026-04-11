"""Shared parsing helpers for line-oriented mmWave cfg files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

COMMENT_MARKERS = frozenset({"%", "#"})

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(slots=True, frozen=True)
class CfgCommand:
    """One parsed command line from a mmWave cfg file."""

    line_no: int
    name: str
    args: tuple[str, ...]
    text: str


def strip_inline_comment(raw_line: str) -> str:
    """Strip one inline cfg comment while preserving command text."""
    for index, char in enumerate(raw_line):
        if char in COMMENT_MARKERS and (index == 0 or raw_line[index - 1].isspace()):
            return raw_line[:index].rstrip()
    return raw_line.rstrip()


def load_cfg_lines(config_path: Path) -> list[str]:
    """Load non-empty cfg command lines with comments removed."""
    return [command.text for command in load_cfg_commands(config_path)]


def load_cfg_commands(config_path: Path) -> list[CfgCommand]:
    """Parse one cfg file into command records."""
    resolved_path = config_path.expanduser().resolve()
    commands: list[CfgCommand] = []

    for line_no, raw_line in enumerate(
        resolved_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = strip_inline_comment(raw_line).strip()
        if not line:
            continue

        parts = line.split()
        commands.append(
            CfgCommand(
                line_no=line_no,
                name=parts[0],
                args=tuple(parts[1:]),
                text=line,
            )
        )

    return commands
