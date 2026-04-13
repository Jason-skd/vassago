"""Standalone 3D Point Cloud Visualizer for IWR6843AOP RD collection workflows."""

import struct
import multiprocessing
from multiprocessing import Queue

try:
    import numpy as np
    import pyqtgraph as pg
    import pyqtgraph.opengl as gl
    from PyQt6 import QtWidgets, QtCore
except ImportError:
    np = None
    pg = None

MAGIC_WORD = b"\x02\x01\x04\x03\x06\x05\x08\x07"

def extract_point_cloud_from_buffer(buffer: bytearray) -> tuple[list[tuple[float, float, float, float]], int]:
    """
    Strictly aligns and extracts Point Cloud TLVs (Type 1) from IWR6843AOP data stream.
    Returns the points and the number of bytes consumed (to advance the buffer).
    """
    if len(buffer) < 8:
        return None, 0

    # 1. 寻找魔法字 (MAGIC WORD Alignment)
    idx = buffer.find(MAGIC_WORD)
    if idx < 0:
        # 如果找不到魔法字，丢弃直到最后 7 个字节（因为魔法字可能被截断在两批数据之间）
        return None, max(0, len(buffer) - 7)

    # 2. 如果魔法字不在开头，说明前面是残缺/错位数据，直接丢弃（对齐操作）
    if idx > 0:
        return None, idx

    # 3. 检查包头长度是否足够 (Header is 40 bytes)
    if len(buffer) < 40:
        return None, 0

    header_format = "<8I"
    try:
        (
            version, total_packet_length, platform, frame_number,
            time_cpu_cycles, num_detected_objects, num_tlvs, sub_frame_number,
        ) = struct.unpack_from(header_format, buffer, 8)
    except struct.error:
        # 包头解析失败，丢弃第一个字节重新寻找魔法字
        return None, 1

    # 4. 长度合理性检查，避免解析到畸形的 total_packet_length 导致内存爆炸
    if total_packet_length < 40 or total_packet_length > 1048576:
        return None, 1

    # 5. 等待完整的数据包到来
    if len(buffer) < total_packet_length:
        return None, 0

    points = []
    offset = 40
    
    # 6. TLV 逐个遍历，严格进行边界检查
    for _ in range(num_tlvs):
        if offset + 8 > total_packet_length:
            break
        tlv_type, tlv_length = struct.unpack_from("<II", buffer, offset)
        
        if tlv_type == 1:  # Point Cloud Type
            # 对于 SDK 3.x，点云 TLV 是 x,y,z,v 四个浮点数 (16字节)
            num_points = tlv_length // 16
            
            # 处理部分固件 tlv_length 包含 8 字节 header 的情况
            if num_points == 0 and tlv_length >= 8:
                num_points = (tlv_length - 8) // 16
            
            payload_offset = offset + 8
            # 严格防止越界读取
            if num_points > 0 and payload_offset + num_points * 16 <= total_packet_length:
                points_data = struct.unpack_from("<" + "f" * (num_points * 4), buffer, payload_offset)
                for i in range(num_points):
                    points.append((
                        points_data[i*4],     # x
                        points_data[i*4+1],   # y
                        points_data[i*4+2],   # z
                        points_data[i*4+3]    # velocity (Doppler)
                    ))
        
        # 移动到下一个 TLV，尝试兼容是否包含 8 字节 header 的长度
        if offset + tlv_length + 8 <= total_packet_length:
            offset += tlv_length + 8
        else:
            offset += tlv_length
        
    return points, total_packet_length


def visualizer_main(data_queue: Queue) -> None:
    """The isolated process that handles parsing and rendering without blocking capture."""
    if np is None or pg is None:
        print("Visualizer skipped: Dependencies (numpy, pyqtgraph, PyQt6, PyOpenGL) not found.")
        return

    app = QtWidgets.QApplication([])
    window = gl.GLViewWidget()
    
    # 核心修改：强制窗口不抢夺焦点，且悬浮在顶层（像一个被动的幽灵窗口）
    window.setWindowFlags(
        QtCore.Qt.WindowType.WindowStaysOnTopHint | 
        QtCore.Qt.WindowType.WindowDoesNotAcceptFocus |
        QtCore.Qt.WindowType.Tool
    )
    # 强制窗口的输入焦点策略为 NoFocus，确保它忽略任何键盘输入
    window.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
    
    window.setWindowTitle("IWR6843AOP 3D Point Cloud Monitor")
    window.setGeometry(100, 100, 800, 600)
    window.show()
    
    # 添加网格
    gx = gl.GLGridItem()
    gx.setSize(5, 5)
    window.addItem(gx)

    # 添加坐标轴
    axis = gl.GLAxisItem()
    window.addItem(axis)

    # 初始化点云 Scatter
    scatter = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), size=5, color=(0.0, 1.0, 0.0, 1.0))
    window.addItem(scatter)

    buffer = bytearray()

    def update_frame():
        # 1. 从队列获取所有堆积的新数据 (非阻塞)
        while not data_queue.empty():
            try:
                chunk = data_queue.get_nowait()
                if chunk is None:  # 收到停止信号
                    app.quit()
                    return
                buffer.extend(chunk)
            except Exception:
                break

        # 2. 循环处理 buffer 中的所有完整数据包，直到不够一个包为止
        latest_points = None
        while True:
            points, consumed_bytes = extract_point_cloud_from_buffer(buffer)
            if consumed_bytes > 0:
                del buffer[:consumed_bytes]  # 对齐并丢弃已处理的字节
                if points is not None:
                    # 只要有数据点（即便是空数组 [] 意味着这一帧没点），都更新
                    latest_points = points
            else:
                break

        # 3. 渲染最新一帧的点云
        if latest_points is not None:
            if len(latest_points) > 0:
                # Y 和 Z 轴在 PyQtGraph 里需要做个旋转映射，让前方对着屏幕内部，高度向上
                # 雷达系：y+ 是前方，x+ 是右边，z+ 是上方
                # PyQtGraph系：一般 y+ 是深度/屏幕内，z+ 是高度
                pos = np.array([[p[0], p[1], p[2]] for p in latest_points])
                vel = np.array([p[3] for p in latest_points])
                
                # 多普勒速度映射到颜色 (这里假设速度范围在 -2 到 2 之间)
                norm_vel = np.clip((vel + 2.0) / 4.0, 0, 1)
                colors = np.zeros((len(latest_points), 4))
                colors[:, 0] = norm_vel       # Red 对应靠近/远离
                colors[:, 1] = 1 - norm_vel   # Green
                colors[:, 2] = 0.5            # Blue
                colors[:, 3] = 1.0            # Alpha 不透明度
                
                scatter.setData(pos=pos, color=colors)
            else:
                # 这一帧没有点，清空显示
                scatter.setData(pos=np.zeros((1, 3)), color=(0,0,0,0))

    # 启动 30FPS 的定时刷新
    timer = QtCore.QTimer()
    timer.timeout.connect(update_frame)
    timer.start(33)
    app.exec()


def start_visualizer() -> tuple[multiprocessing.Process, Queue] | tuple[None, None]:
    """Start visualizer process safely. Returns process and queue."""
    if np is None or pg is None:
        return None, None
        
    data_queue = multiprocessing.Queue()
    proc = multiprocessing.Process(target=visualizer_main, args=(data_queue,))
    proc.daemon = True
    proc.start()
    return proc, data_queue


def stop_visualizer(proc: multiprocessing.Process, data_queue: Queue) -> None:
    """Gracefully signal visualizer to stop."""
    if proc is not None and proc.is_alive():
        try:
            data_queue.put(None)
            proc.join(timeout=0.5)
            if proc.is_alive():
                proc.terminate()
        except Exception:
            pass