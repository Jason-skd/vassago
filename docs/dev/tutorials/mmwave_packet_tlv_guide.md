# mmWave `packet(frame)`、TLV 与点云帧心智模型

这篇文档是写给“准备理解、调试或扩展 mmWave UART 数据链路”的人看的。

它只回答一件事：

- `chunk`
- `raw_capture`
- `packet(frame)`
- `TLV`
- `point_cloud_frame`

这些词分别是什么意思，它们在当前仓库里处于哪一层。

如果你正在看 live capture、`summary`、`quick_qc`、点云可视化或后续切割方案，
先把这篇文档里的层次关系搞清楚。

## 1. 先建立正确心智模型

当前仓库里的 mmWave Data UART 数据，不应理解成“收到一堆独立 TLV，再按时间拼起来”。

更准确的结构是：

```text
serial data stream
  -> chunk
  -> packet/frame
  -> TLVs inside one packet
  -> semantic decoded result
```

可以直接记成一句话：

- 串口上流动的是字节流
- 程序一次次读到的是 `chunk`
- parser 对齐后拿到的是 `packet/frame`
- 一帧里面再包含若干个 TLV
- 点云帧是某些 TLV 被解码后的语义结果，不是线上的原始结构

## 2. `chunk` 是什么

`chunk` 指的是一次串口读取操作拿到的一小段原始 `bytes`。

在当前仓库里，它对应：

- `connection.read(read_size)` 的返回值

也就是说：

- `chunk` 不是物理端口
- `chunk` 不是完整一帧
- `chunk` 只是“这一次 read 拿到的若干字节”

它可能：

- 刚好只包含半个 packet
- 包含一个完整 packet
- 包含多个 packet
- 从一个 packet 尾巴开始，再接上下一个 packet 头

因此任何业务逻辑都不应假设“一个 `chunk` 就是一个完整业务单位”。

## 3. `raw_capture` 和 `raw_uart.bin` 是什么

`raw_capture` 指的是一次 `capture_window` 内累计下来的完整原始字节缓存。

它可以理解成：

```text
raw_capture = chunk1 + chunk2 + chunk3 + ...
```

在 capture 结束后，`raw_capture` 会被写成 `raw_uart.bin`。

所以关系是：

- `chunk`
  - 一次 read 的瞬时原始字节片段
- `raw_capture`
  - 单次采集窗口内的完整原始字节缓存
- `raw_uart.bin`
  - `raw_capture` 的持久化文件

一句话记忆：

- `raw_capture` 是 `.bin` 的内存上游

## 4. `packet(frame)` 是什么

`packet` 或 `frame` 是 parser 对齐后得到的“时间维度上的一个完整 mmWave 包”。

当前仓库的 `MmwavePacketParser` 负责把原始字节流恢复成这一层对象。

在协议层，一个 packet 至少包含：

- magic word
- 固定 header
- `num_tlvs`
- 后续若干个 TLV

当前仓库里固定长度的部分是：

- magic word: `8` 字节
- header body: `32` 字节
- 因此 packet 固定头总长: `40` 字节

可以把一个 packet 想成：

```text
packet/frame
  = 40B fixed header
  + TLV #1
  + TLV #2
  + ...
```

当前 `MmwavePacket` 暴露的主要是：

- `frame_number`
- `num_tlvs`
- `tlv_types`
- 其他 header 字段

注意：

- 一个 packet 不是“几组 TLV 的时间窗口”
- 一个 packet 就是一帧
- TLV 是这一帧内部的子块

## 5. TLV 是什么

TLV 是 `Type-Length-Value` 的缩写。

可以把它理解成“一个 packet 里的一个数据块”。

每个 TLV 都有自己的小头：

- `type`
- `length`

后面才是 payload。

在当前仓库里，TLV header 固定长度是：

- `8` 字节

因此一个 TLV 可以想成：

```text
TLV
  = 8B tlv header
  + variable-length payload
```

一帧里可以有多个 TLV，例如：

```text
packet(frame #128)
  -> TLV type=1   # 点云
  -> TLV type=6   # 统计或附加信息
  -> TLV type=7   # 其他数据
```

最重要的区分是：

- TLV 不是一组帧
- TLV 是一帧内部的一段数据

## 6. `point_cloud_frame` 是什么

`point_cloud_frame` 是一个语义层名字，用来表达：

- 从 packet 内某个点云 TLV 解码后
- 得到的一帧点云结果

它不是线上原始协议结构名，而是上层更适合消费的业务对象名。

当前仓库里还没有正式定义这个类型，但在现有 visualizer 实现里，点云的实际数据形态已经接近它：

```python
list[tuple[float, float, float, float]]
```

每个点表示：

- `x`
- `y`
- `z`
- `v`（velocity / Doppler）

如果后续把它收敛成正式类型，更合理的形态通常会接近：

```python
PointCloudFrame(
    frame_number=128,
    relative_time_s=1.73,
    points=[(x, y, z, velocity), ...],
)
```

这里要特别注意：

- `point_cloud_frame` 不是 TLV 本身
- 它是 TLV 解码后的语义结果

## 7. 当前仓库里各层分别由谁负责

当前仓库大致已经有下面这些层次：

### 原始字节与采集窗口

- `src/vassago/collection/rd/capture.py`

这里负责：

- 串口读取
- 把每次 read 得到的 `chunk` 追加进 `raw_capture`
- 在 capture 结束后写出 `raw_uart.bin`

### packet 级解析

- `src/vassago/firmware/mmwave/protocol.py`

这里负责：

- magic word 对齐
- packet header 解析
- TLV type 最佳努力解析
- packet summary 统计

### 点云解码与可视化

- `src/vassago/collection/rd/visualizer.py`

当前这里仍然同时承担了两件事：

- 自己重做 packet/TLV 解析
- 把点云画出来

这正是后续准备收敛的地方：解析层应逐步从 GUI 模块里拆出来。

## 8. 一个完整数据流例子

当前更接近真实情况的数据流，可以这样理解：

```text
Data UART bytes
-> chunk
-> append into raw_capture
-> parser aligns bytes into packet/frame
-> parser finds TLVs inside packet
-> point-cloud decoder reads TLV type=1
-> point_cloud_frame
-> GUI / cache / cutting tool consume that frame
```

而 `summary` / `quick_qc` 当前更接近：

```text
raw_capture
-> packet parser
-> packet summary
-> QC decision
```

后续重构的目标，就是让 live capture、replay、GUI、QC 尽量共用同一条 parser 路线。

## 9. 为什么 TLV 兼容差异值得单独注意

当前协议层和 visualizer 都已经暴露出一个现实问题：

- 某些固件把 `tlv_length` 写成 payload 长度
- 某些固件把 `tlv_length` 写成 TLV 总长度

这类差异如果处理错了，会直接导致：

- TLV 边界错位
- 后续 TLV 偏移
- 点数计算错误
- 本来有点云却被解析成空帧
- live 画面看起来随机丢帧或失真

所以这类兼容问题的正确归属是：

- parser / decoder 层

而不是：

- GUI 显示层
- operator 输入层

## 10. 最容易混淆的 5 组概念

### `chunk` 和 `packet`

- `chunk` 是一次 read 拿到的字节片段
- `packet` 是 parser 对齐后的完整一帧

### `raw_capture` 和 `raw_uart.bin`

- `raw_capture` 是内存中的完整原始缓存
- `raw_uart.bin` 是它落盘后的文件

### `packet` 和 `TLV`

- `packet` 是一帧
- `TLV` 是一帧内部的数据块

### `TLV` 和 `point_cloud_frame`

- `TLV` 是协议层块
- `point_cloud_frame` 是语义层结果

### `GUI 数据` 和 `点云缓存`

- GUI 数据通常是为渲染准备的 `numpy` 位置和颜色
- 点云缓存应该是更接近语义层的 frame 结果

后者更适合复用于：

- 采后切割
- replay
- 派生产物导出

## 11. 一句话总结

当前仓库这条链的正确理解方式是：

```text
字节流 -> chunk -> raw_capture -> packet/frame -> TLV -> 语义解码结果
```

如果你把 `packet` 和 `TLV` 的层次看反了，后面看 live capture、visualizer、QC、
缓存和切割设计时就很容易全部看乱。
