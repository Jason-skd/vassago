"""Temporary no-op visualizer hooks during capture pipeline refactor."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import multiprocessing
    from multiprocessing import Queue


def start_visualizer() -> tuple[None, None]:
    """Return a disabled visualizer handle while integration is paused."""
    return None, None


def stop_visualizer(
    proc: multiprocessing.Process | None,
    data_queue: Queue | None,
) -> None:
    """Accept disabled visualizer handles and do nothing."""
    del proc
    del data_queue
