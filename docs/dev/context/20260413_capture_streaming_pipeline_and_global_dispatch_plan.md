# Live Capture 流式解析链路、可插拔 Consumer 与全局配置扩展计划

## Meta

- Date: 2026-04-13
- Scope: capture
- Status: active
- Requested By: Jason-skd
- Authors:
  - Jason-skd
  - Codex
- Related Branch: `main`
- Related Commits:
  - pending
- Related Files:
  - `src/vassago/collection/rd/capture.py`
  - `src/vassago/collection/rd/visualizer.py`
  - `src/vassago/collection/rd/offline_qc.py`
  - `src/vassago/collection/rd/quick_qc.py`
  - `src/vassago/collection/rd/session.py`
  - `src/vassago/collection/rd/config.py`
  - `src/vassago/firmware/mmwave/protocol.py`
  - `configs/collection/rd/global.toml`
  - `configs/firmware/mmwave/rd_candidate.cfg`
  - `docs/dev/context/20260411_capture_runtime_window_and_global_config_plan.md`
  - `docs/dev/context/20260412_capture_qc_boundary_and_manifest_public_contract.md`

## Background

当前仓库已经具备：

- `raw_uart.bin` 为核心产物的 RD collection 采集链路
- 以 `capture_window / target_window / marked_window` 为核心的窗口契约
- live `quick_qc` 与离线 `offline_qc` replay
- 基于 `MmwavePacketParser` 的最小 packet 级解析与 summary

最新提交为 `rd_candidate.cfg` 打开了点云输出，并在 `collection.rd.visualizer`
中新增了 3D 点云可视化。但当前实现仍有几个关键特征：

- 可视化链路在自己的模块中重新执行 magic word 对齐、packet header 解析和 TLV 遍历
- live capture 主路径与 visualizer 子进程之间传的是原始串口 `chunk`
- visualizer queue 当前是 best-effort，失败时允许直接丢数据
- `summary` 与 `quick_qc` 仍主要在 capture 结束后基于完整 `raw_capture` 执行

同一轮讨论中，后续主线进一步明确为：

- 点云解析需要从“GUI 专用实现”提升为可复用的解码层
- live capture、离线 replay、未来切割流程应尽量共用同一套权威解析路线
- `raw_uart.bin` 继续作为唯一真源
- 点云缓存是派生缓存，不应反客为主替代真源
- `verify_window` 与切割工作应在完成解析链和 consumer 边界重构后再进入主线
- `global.toml` 的长期目标是让仓库在换板子、换固件时具备更强迁移能力

## Decision / Findings

### 1. `raw_uart.bin` 继续是唯一真源

当前正式固定：

- `chunk`
  - 指一次 `connection.read(read_size)` 读到的一段原始 `bytes`
  - 是串口数据流上的瞬时片段，不是物理端口
- `raw_capture`
  - 指单次 `capture_window` 期间累计的完整原始字节缓存
  - 是 `raw_uart.bin` 的直接上游
- `raw_uart.bin`
  - 继续作为 capture 的唯一真源持久化产物

任何 live 解析结果、点云缓存、GUI 状态或 `.npz` 派生产物，都不应替代
`raw_uart.bin` 的 source-of-truth 地位。

### 2. packet(frame) 与 TLV 的语义分层固定为“帧包含多个 TLV”

当前正式固定以下心智模型：

```text
raw UART byte stream
  -> chunk
  -> packet/frame
  -> TLVs inside one packet
```

也就是说：

- 时间维度上的最小完整单位是 `packet/frame`
- 一帧内部包含：
  - 固定 header
  - 若干个 `TLV(type-length-value)` 数据块
- 点云不是“几帧 TLV 的集合”
- 点云是“某些 packet 中特定 TLV 被解码后的语义结果”

未来如需写稳定 tutorial，应基于这份 context 继续整理，但 tutorial 本身不属于本次主线任务。

### 3. live capture 应引入唯一权威的实时 parser

当前正式固定：

- live capture 主路径中应存在唯一权威的实时 parser
- 这条 parser 路线负责：
  - buffer 对齐
  - packet header 解析
  - TLV 边界判定
  - 为上层 decoder 提供统一输入
- GUI 不再承担协议正确性的职责
- `summary`、`quick_qc`、点云 decoder、未来 RD decoder、离线 replay，应尽量共用这条 parser 路线

当前不再接受的方向是：

- visualizer 单独维护一套长期存在的 packet/TLV 解析逻辑
- `summary` / `QC` / GUI 各自拿原始字节再独立解析一遍

### 4. live capture 应发布“解析后事件流”，而不是让插件直接啃原始串口

当前正式固定的链路方向为：

```text
serial read
-> append raw_capture
-> authoritative parser
-> parsed event stream
   -> summary consumer
   -> quick-qc consumer
   -> point-cloud decoder
      -> GUI consumer
      -> point-cloud cache consumer
```

这意味着：

- capture 主链只负责：
  - 读串口
  - 累积原始字节
  - 驱动权威 parser
  - 发布解析后事件
- 上层模块通过 consumer 接口接入
- 上层模块默认不直接读串口，也不自己做 packet 对齐

### 5. `summary` 与 `quick_qc` 也应是 consumer，而不是 capture 的内嵌特判逻辑

当前正式固定：

- `summary`
  - 视为 packet/event 流上的轻量累加 consumer
- `quick_qc`
  - 视为 packet/event 流或 summary 上游结果的 consumer
- 二者都不应再被设计成“只能在 5 秒结束后才第一次拥有解析能力”

实现上允许第一阶段仍在 capture 结束后统一收口结果，但能力边界应先切成
consumer，而不是继续耦合为 capture 内部专用分支。

### 6. consumer 接口与执行策略必须解耦

当前正式固定：

- 先定义统一 consumer 接口
- 再决定其执行策略
- “并发/并行”属于运行策略，不属于业务抽象本身

第一阶段默认策略为：

- `summary`
  - `inline`
  - 同步、同进程
- `quick_qc`
  - `inline`
  - 同步、同进程
- GUI
  - 允许继续独立进程
  - 但改为消费解析后的点云语义结果，而不是自己重解原始字节

当前不要求立刻实现“运行时关闭某个 consumer”的产品能力，但接口与 runner
边界应确保后续能够低成本插拔。

### 7. 点云缓存是切割与可视化的派生缓存，不是 `rd.npz` 前置依赖

当前正式固定：

- `point_cloud_frame` 一类的语义缓存值得保留
- 这份缓存主要服务于：
  - 点云可视化
  - operator 采后切割
  - 未来可能的点云派生产物
- 当前不要求 `rd.npz` 依赖该缓存

这意味着：

- `rd.npz` 仍可独立由 RD 路径从 `raw_uart.bin` 派生
- 点云缓存不应绑架 RD 路线
- 点云缓存若要落地，应至少保留：
  - `frame_number`
  - 时间定位信息（如 `relative_time_s` 或等效字段）
  - 点云点集本身

### 8. live 与 replay 应复用同一套 decoder，而不是分成 GUI-only 和 offline-only 两套

当前正式固定：

- 同一份 decoder 应同时支持：
  - live capture 流式消费
  - 针对已存在 `raw_uart.bin` 的离线 replay
- 不接受“GUI 使用一套私有点云解析，而 replay/离线切割再写一套”的方向

未来如需新增单独命令，应允许：

- 从已有 `raw_uart.bin` 重新提取点云 frame
- 对已有数据运行切割和导出

但这些都应建立在同一套 decoder 库层之上。

### 9. “双采集”在实现上收敛为“一次采集，多路 decoder”

当前正式固定：

- 如果同一条 Data UART 流中同时携带多种 TLV
- 实现上应优先收敛为：
  - 一个 collector
  - 一个权威 parser
  - 多个业务 decoder

而不是：

- point cloud 一套 capture 主链
- RD 再一套 capture 主链

也就是说，当前讨论中的“点云 + RD 双采集”在代码结构上更准确的目标是：

- 一次真实采集
- 多个派生解码视图

### 10. TLV 兼容差异属于迁移配置问题，但不应继续散落在 GUI 模块里

当前已经明确存在的兼容风险包括：

- 某些固件把 `tlv_length` 当作 payload 长度
- 某些固件把 `tlv_length` 当作 TLV 总长度

如果处理错误，会导致：

- TLV 边界错位
- 后续 TLV 偏移
- 点数统计错误
- 明明有点云却解析成空帧
- live 画面抖动或看起来“随机失真”

当前正式固定：

- 这类兼容逻辑应提升为 parser/decoder 层的显式能力
- 不再允许长期散落在 GUI 专用模块内
- 这类差异属于“换板子、换固件时可能需要迁移”的信息
- 因此更适合归入全局迁移配置，而不是继续硬编码在 `collection.runtime` 里

### 11. `global.toml` 的长期方向改为“单一迁移入口 + dispatcher”

当前正式固定的方向是：

- 延续单一 `global.toml` 的入口地位
- 让它逐步从“仅服务 collection 预设”的全局配置，扩展为“仓库迁移入口”
- 通过 dispatcher 把不同子域配置分发给对应 loader / parser

当前明确不采用的做法是：

- 为每个 parser 单独新开一份互不关联的全局 TOML，导致迁移入口再次分裂

### 12. `global.toml` 的 dispatcher 采用 section-based 分发，不采用字段级消费注册表

本轮讨论中，曾认真考虑过“记录每个字段被哪些 parser 消费”的字段级 registry。

当前倾向收敛为：

- `global.toml` 内部通过命名 section 表达不同子域
- loader/consumer 通过 section path 或 `parser_id` 找到自己需要的配置块
- dispatcher 负责把整段配置交给对应 loader 校验和消费

建议方向示意如下：

```toml
schema_version = "collection_global_v2"

[collection.runtime]
capture_window_duration_s = 5.0
countdown_duration_s = 5.0
marked_window_end_grace_s = 0.25
end_mark_key = "space"

[serial]
cli_baudrate = 115200
data_baudrate = 921600

[transport.mmwave_uart]
transport_id = "ti_mmwave_uart_v1"

[decoder.point_cloud]
parser_id = "ti_detected_points_v1"
tlv_type = 1
tlv_length_mode = "auto"
point_format = "xyzv_float32"
```

当前不建议第一阶段就做：

- `field -> consumer` 粒度的消费注册表
- 每个字段被哪些 parser 消费的全量维护系统

原因是：

- 复杂度高
- 心智负担大
- 极易把配置入口重新做成隐式依赖仓库

### 13. `verify_window` 与切割工作推迟到解析链和 consumer 重构落地后

当前正式固定：

- `verify_window` 不是本轮重构主线
- 先落稳：
  - 权威 parser
  - 解码层
  - consumer 边界
  - 点云缓存语义
- 再进入切割与 `verify_window`

后续如果新增 `verify_window`，当前仍优先沿用：

- `WindowRange(start_s, end_s)` 的秒域表达

以尽量减少对现有 window / QC / manifest contract 的破坏。

## Alternatives Considered

### 1. 继续让 visualizer 维护自己的 packet/TLV 解析链

没有采用。

原因：

- 解析逻辑重复
- live 与 replay 口径分叉
- 难以复用到点云缓存和后续切割
- GUI 变成协议正确性的隐式 owner

### 2. 让每个 live 插件都直接消费原始 `chunk` 并各自解析

没有采用。

原因：

- 解析链继续分叉
- CPU 开销重复
- 不同消费者可能对同一份原始数据得出不同结论
- 更难确认哪个结果才是权威口径

### 3. 一开始就把所有 consumer 都做成并发线程/进程

没有采用。

原因：

- 生命周期和错误传播更复杂
- 调试时会把协议问题与并发问题混在一起
- `summary` / `quick_qc` 当前更适合同步、确定性的累加模式

### 4. 为 parser/decoder 体系另起一套独立全局 TOML

当前没有采用。

原因：

- 与“单一迁移入口”的长期目标冲突
- 会把换板子、换固件时需要查看的入口再次分裂

### 5. 在 `global.toml` 中维护字段级消费 registry

当前没有采用为第一阶段方案。

原因：

- 与 section-based dispatcher 相比复杂度更高
- 对配置维护者不友好
- 很容易把简单迁移信息扩写成脆弱的元配置系统

## Consequences

这项决策将带来以下影响：

- 会简化什么
  - live / replay / GUI / QC / summary 的解析口径会被收口到同一路线
  - 点云解析可从 GUI 专用逻辑提升为可复用库层
  - 后续切割与缓存的设计边界会更清晰
- 会约束什么
  - 新增 consumer 时优先接解析后事件流，而不是直接碰串口或裸字节
  - parser/decoder 的兼容处理必须走统一配置与统一实现
  - GUI 不再允许长期承担协议层职责
- 会推迟什么
  - `verify_window` 设计与 operator 切割工作
  - 稳定 tutorial 的整理
  - 真正的运行时“关闭某个 consumer”产品能力
- 会带来哪些必要动作
  - 扩展 `firmware.mmwave.protocol` 暴露更可复用的 packet/TLV 结果
  - 定义 consumer 接口与 capture runner
  - 设计点云语义缓存结构
  - 扩展 `global.toml` schema 与 dispatcher

## Next Actions

1. 先重构 mmWave 协议层，使 packet/TLV payload 能被上层 decoder 可靠消费。
2. 定义 live capture 的 consumer 接口，以及默认同步 runner。
3. 把 `summary`、`quick_qc`、点云 decoder 接到同一条解析后事件流。
4. 把 visualizer 改成点云语义结果的 consumer，而不是原始字节解析器。
5. 设计 `point_cloud_frame` 一类的缓存结构与 replay 入口。
6. 扩展 `configs/collection/rd/global.toml` 为 section-based 的迁移入口，并补齐 dispatcher。
7. 在上述基础上，再进入 `verify_window`、切割和相关命令设计。

## Verification / Open Questions

已确认：

- `collection.rd.capture` 当前会把串口 `chunk` 累积进 `raw_capture`，并最终写出 `raw_uart.bin`
- 当前 visualizer 通过独立进程重新解析原始字节，而非消费统一解析结果
- 当前 `offline_qc` 通过重读 `raw_uart.bin` replay `quick_qc`
- 最新提交已把 `configs/firmware/mmwave/rd_candidate.cfg` 的 `guiMonitor` 第一位从 `0` 改为 `1`，即新增点云输出

尚未通过当前仓库完全确认：

- `rd_candidate.cfg` 在当前固件下的完整 TLV 组合与真实 RD 输出形态
- 点云 TLV 的全部兼容模式是否只需 `tlv_length_mode` 一类配置即可覆盖
- `global.toml` 扩展后，是否仍保持当前文件名不变，还是需要引入版本化迁移路径

当前保留的开放问题：

- `point_cloud_frame` 的最小字段集最终应如何命名
- point cloud 与未来 RD decoder 的时间对齐字段最终采用什么口径
- `global.toml` 中 section 的最终命名与版本策略
