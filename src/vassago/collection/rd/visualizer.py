"""Point-cloud visualizer consumer for RD capture workflows."""

from __future__ import annotations

import multiprocessing
import queue
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from vassago.firmware.mmwave.point_cloud import PointCloudFrame
from vassago.firmware.mmwave.point_cloud import extract_point_cloud_frame

if TYPE_CHECKING:
    from multiprocessing import Queue

    from vassago.firmware.mmwave.protocol import MmwavePacket


try:
    import numpy as np
    import pyqtgraph.opengl as gl
    from PyQt6 import QtCore
    from PyQt6 import QtWidgets
except ImportError:
    gl = None
    np = None
    QtCore = None
    QtWidgets = None

FRAME_QUEUE_MAXSIZE = 2
FRAME_INTERVAL_MS = 33
FRAME_QUEUE_STOP = None
VELOCITY_COLOR_ABS_MAX = 2.0
VISUALIZER_JOIN_TIMEOUT_SECONDS = 0.5


@dataclass(slots=True)
class PointCloudVisualizerSession:
    """Live visualizer process plus its packet-consumer hook."""

    process: multiprocessing.Process | None = None
    frame_queue: Queue | None = None

    @property
    def enabled(self) -> bool:
        """Return whether a child visualizer process is active."""
        return self.process is not None and self.frame_queue is not None

    def consume_packets(self, packets: tuple[MmwavePacket, ...]) -> None:
        """Decode point-cloud frames from parsed packets and queue them for display."""
        if self.frame_queue is None:
            return

        for packet in packets:
            try:
                frame = extract_point_cloud_frame(packet)
            except ValueError:
                continue
            if frame is None:
                continue
            _enqueue_latest_frame(self.frame_queue, frame)

    def close(self) -> None:
        """Stop the child process when the live capture finishes."""
        if self.process is None:
            return

        if self.frame_queue is not None:
            with suppress(queue.Full, OSError, ValueError):
                self.frame_queue.put_nowait(FRAME_QUEUE_STOP)

        self.process.join(timeout=VISUALIZER_JOIN_TIMEOUT_SECONDS)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=VISUALIZER_JOIN_TIMEOUT_SECONDS)


def start_visualizer(*, enabled: bool) -> PointCloudVisualizerSession:
    """Start the child visualizer process when explicitly enabled."""
    if not enabled or not _visualizer_dependencies_available():
        return PointCloudVisualizerSession()

    frame_queue = multiprocessing.Queue(maxsize=FRAME_QUEUE_MAXSIZE)
    process = multiprocessing.Process(
        target=visualizer_main,
        args=(frame_queue,),
    )
    process.daemon = True
    try:
        process.start()
    except OSError, RuntimeError:
        return PointCloudVisualizerSession()
    return PointCloudVisualizerSession(
        process=process,
        frame_queue=frame_queue,
    )


def visualizer_main(frame_queue: Queue) -> None:
    """Run the isolated GUI loop that renders the latest decoded point cloud."""
    np_module = np
    gl_module = gl
    qt_core = QtCore
    qt_widgets = QtWidgets
    if None in (np_module, gl_module, qt_core, qt_widgets):
        return
    np_module = cast("Any", np_module)
    gl_module = cast("Any", gl_module)
    qt_core = cast("Any", qt_core)
    qt_widgets = cast("Any", qt_widgets)

    app = qt_widgets.QApplication([])
    window = gl_module.GLViewWidget()
    window.setWindowFlags(
        qt_core.Qt.WindowType.WindowStaysOnTopHint
        | qt_core.Qt.WindowType.WindowDoesNotAcceptFocus
        | qt_core.Qt.WindowType.Tool
    )
    window.setFocusPolicy(qt_core.Qt.FocusPolicy.NoFocus)
    window.setWindowTitle("IWR6843AOP 3D Point Cloud Monitor")
    window.setGeometry(100, 100, 800, 600)
    window.setCameraPosition(distance=6)

    grid = gl_module.GLGridItem()
    grid.setSize(5, 5)
    window.addItem(grid)

    axis = gl_module.GLAxisItem()
    window.addItem(axis)

    scatter = gl_module.GLScatterPlotItem(
        pos=np_module.zeros((1, 3), dtype=float),
        size=5,
        color=(0.0, 0.0, 0.0, 0.0),
    )
    window.addItem(scatter)
    window.show()

    def update_frame() -> None:
        stop_requested, latest_frame = _drain_frame_queue(frame_queue)
        if latest_frame is not None:
            _render_point_cloud_frame(scatter=scatter, frame=latest_frame)
        if stop_requested:
            app.quit()

    timer = qt_core.QTimer()
    timer.timeout.connect(update_frame)
    timer.start(FRAME_INTERVAL_MS)
    app.exec()


def _visualizer_dependencies_available() -> bool:
    """Return whether all optional GUI dependencies imported successfully."""
    return all(module is not None for module in (np, gl, QtCore, QtWidgets))


def _enqueue_latest_frame(
    frame_queue: Queue,
    frame: PointCloudFrame,
) -> None:
    """Queue the latest frame and drop stale backlog when necessary."""
    try:
        frame_queue.put_nowait(frame)
    except queue.Full:
        _drop_stale_frame(frame_queue)
    except OSError, ValueError:
        return
    else:
        return

    try:
        frame_queue.put_nowait(frame)
    except queue.Full, OSError, ValueError:
        return


def _drop_stale_frame(frame_queue: Queue) -> None:
    """Best-effort removal of one queued frame to keep the GUI current."""
    try:
        frame_queue.get_nowait()
    except queue.Empty:
        return
    except OSError, ValueError:
        return


def _drain_frame_queue(
    frame_queue: Queue,
) -> tuple[bool, PointCloudFrame | None]:
    """Drain the queue and keep only the newest frame for rendering."""
    latest_frame: PointCloudFrame | None = None
    stop_requested = False

    while True:
        try:
            item = frame_queue.get_nowait()
        except queue.Empty:
            return stop_requested, latest_frame
        except OSError, ValueError:
            return stop_requested, latest_frame

        if item is FRAME_QUEUE_STOP:
            stop_requested = True
            continue
        latest_frame = item


def _render_point_cloud_frame(*, scatter: object, frame: PointCloudFrame) -> None:
    """Render one semantic point-cloud frame into the scatter plot."""
    np_module = np
    if np_module is None:
        return
    np_module = cast("Any", np_module)
    scatter_item = cast("Any", scatter)

    if frame.point_count == 0:
        scatter_item.setData(
            pos=np_module.zeros((1, 3), dtype=float),
            color=(0.0, 0.0, 0.0, 0.0),
        )
        return

    positions = np_module.array(
        [(point.x, point.y, point.z) for point in frame.points],
        dtype=float,
    )
    velocities = np_module.array(
        [point.velocity for point in frame.points],
        dtype=float,
    )
    normalized_velocity = np_module.clip(
        (velocities + VELOCITY_COLOR_ABS_MAX) / (2 * VELOCITY_COLOR_ABS_MAX),
        0.0,
        1.0,
    )
    colors = np_module.zeros((frame.point_count, 4), dtype=float)
    colors[:, 0] = normalized_velocity
    colors[:, 1] = 1 - normalized_velocity
    colors[:, 2] = 0.5
    colors[:, 3] = 1.0
    scatter_item.setData(pos=positions, color=colors)
