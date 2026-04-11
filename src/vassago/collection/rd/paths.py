"""Path helpers shared by RD collection modules."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Return the repository root from inside the package tree."""
    return Path(__file__).resolve().parents[4]


def resolve_repo_path(path_value: str | Path) -> Path:
    """Resolve a repository-relative or absolute path to an absolute path."""
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (repo_root() / path).resolve()


def to_repo_relative_path(path: Path) -> str:
    """Render a path relative to the repository when possible."""
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(repo_root()).as_posix()
    except ValueError:
        return str(resolved_path)
