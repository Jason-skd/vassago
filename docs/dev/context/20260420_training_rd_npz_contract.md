# RD `.npz` Canonical Sample Contract

## Meta

- Date: 2026-04-20
- Scope: training
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
  - `src/vassago/collection/rd/session.py`
  - `src/vassago/collection/rd/qc_contract.py`
  - `src/vassago/firmware/mmwave/protocol.py`
  - `configs/collection/rd/global.toml`
  - `docs/dev/context/20260412_capture_qc_boundary_and_manifest_public_contract.md`
  - `docs/dev/context/20260413_capture_streaming_pipeline_and_global_dispatch_plan.md`
  - `docs/dev/tutorials/collection-toml-authoring.md`

## Background

当前仓库已经明确：

- `raw_uart.bin` 是 RD collection 的原始持久化产物
- manifest 顶层字段是 downstream tooling 的公共 contract
- 后续机器学习希望以 `.npz` 作为唯一消费入口

同一轮讨论中，进一步收敛出了以下要求：

- `rd.npz` 不应只是临时训练缓存，而应成为机器学习侧的 canonical sample
- `rd.npz` 不应裁掉 5 秒主数据，只因 `target_window` 或 `marked_window`
- `target_window` 与 `marked_window` 应进入 `.npz`，但作为标签或时间元数据，而不是替代主数据
- `rd.npz` 不应演变成归档包、debug bundle 或 manifest 镜像
- 当前 `.bin` / packet replay 路线尚不能完美恢复“每一帧相对 `capture_window.start` 的真实秒偏移”，因此不应强行在 `v1` 中捏造 `relative_time_s`

这要求新增一份 context，固定：

- `raw_uart.bin` 与 `rd.npz` 在 source-of-truth 上的分工
- `rd.npz v1` 的最小字段集合
- 哪些信息属于 canonical sample
- 哪些信息虽然可记录，但当前不进入 canonical `.npz`

## Decision / Findings

### 1. source-of-truth 分为采集侧与机器学习侧两层

当前正式固定：

- `raw_uart.bin`
  - 继续作为采集侧 source-of-record
  - 负责保留原始 UART 字节真源
- `rd.npz`
  - 作为机器学习侧 canonical sample
  - 后续训练、评估与数据集消费默认只读取 `.npz`

这不是让 `.npz` 取代 `raw_uart.bin` 的采集真源地位，而是固定：

- capture truth: `raw_uart.bin`
- ML-facing truth: `rd.npz`

### 2. 导出粒度固定为“一个 accepted take 对应一个 `rd.npz`”

当前正式固定：

- 不按整个 session 打一个大 `.npz`
- 每个 accepted take 独立导出一份 `rd.npz`

原因：

- 与现有 `take_id` 和 `raw_uart.bin` 产物结构天然对齐
- 单样本重跑、跳过、替换更简单
- training loader 可直接按样本文件组织，而不是回头理解整轮 session

### 3. 主数据始终保留完整 5 秒 `capture_window`

当前正式固定：

- `rd` 主数据始终表达完整的 5 秒 `capture_window`
- `target_window` 与 `marked_window` 不用于裁掉主数据
- 它们作为标签或时间元数据进入 `.npz`

这意味着：

- canonical sample 表达的是“完整录制窗口”
- 训练、评估、激活检测等具体任务，如需裁切、mask 或 fixed-shape 变换，应在消费 `.npz` 时再派生

当前不采用的方向是：

- 在 canonical `.npz` 中只保存 `target_window` 内部数据
- 同时保存多份裁切后的派生主数据
- 将 `target_window` / `marked_window` 直接塞进 `rd` 的额外信号通道

### 4. `relative_time_s` 不进入 `v1` 必填 contract

当前正式固定：

- `relative_time_s` 当前不进入 `rd.npz v1` 必填字段
- 也不写入近似时间来冒充真实时间

原因：

- 当前 `raw_uart.bin` 能稳定重放出 packet/frame 顺序、`frame_number` 和 `time_cpu_cycles`
- 但当前持久化产物并没有稳定落盘“每帧相对 `capture_window.start` 的真实秒偏移”
- 因此当前实现不能完美支持真实 `relative_time_s`

若未来需要该能力，应重新单独讨论：

- 是否在 capture 阶段新增 sidecar 时间索引
- 是否让 `relative_time_s` 进入后续 schema 版本

### 5. `rd.npz v1` 只保留训练必需且无法从 `rd` 反推出的上下文

当前正式固定：

- canonical `.npz` 不做“全 manifest 镜像”
- canonical `.npz` 也不做“parser/debug/audit bundle”
- `v1` 只保留：
  - 主数据
  - 时间窗口标签
  - 训练与数据集管理必需、但无法从 `rd` 直接反推的上下文字段

因此，当前 `rd.npz v1` 的最小字段集合固定为：

- `schema_version`
- `rd`
- `capture_window_s`
- `target_window_s`
- `marked_window_s`
- `gesture`
- `subject_name`
- `hand`
- `distance_m`
- `angle_deg`
- `environment`
- `radar_id`
- `firmware_id`
- `firmware_config_id`
- `session_id`
- `take_id`

说明：

- `subject_name`
  - 当前仓库已有稳定来源字段，因此先沿用它
  - 若未来 session contract 引入稳定的 `subject_id`，可在后续 schema 版本中再讨论迁移
- `session_id` / `take_id`
  - 对训练本身不是张量内容必需
  - 但对坏样本回查、去重与数据泄漏排查有实际价值，因此保留

### 6. 以下信息当前不进入 canonical `.npz`

当前正式固定，不进入 `rd.npz v1` 的信息包括：

- parser replay 摘要字段，例如：
  - `valid_packet_count`
  - `invalid_packet_count`
  - `frame_gap_count`
  - `non_monotonic_frame_count`
  - `packet_frame_number`
  - `packet_time_cpu_cycles`
- 追溯与审计字段，例如：
  - `source_raw_uart_sha256`
  - `source_raw_uart_nbytes`
  - `extractor_version`
- 原始结构镜像，例如：
  - `source_manifest_json`
  - `source_take_json`
  - `source_config_snapshot_json`
- 非训练必需的操作上下文字段，例如：
  - `operator_name`
  - `cli_port`
  - `data_port`
  - `gesture_options`
  - `environment_options`

原因：

- 这些字段要么可重算、要么偏调试、要么偏审计、要么偏管理
- 放进 canonical `.npz` 会把训练样本与 debug bundle 混在一起
- 当前目标是让 `.npz` 作为机器学习输入契约，而不是替代原始归档

## Alternatives Considered

### 1. 让 `.npz` 直接替代 `raw_uart.bin` 成为唯一真源

当前没有采用。

原因：

- 与既有 capture truth 设计冲突
- 会削弱对原始 UART 真源的保留
- 把训练契约与采集归档契约混成一层

### 2. 在 canonical `.npz` 中只保存窗口裁切后的主数据

当前没有采用。

原因：

- 不利于未来同时支持手势识别与激活检测
- 会让切窗策略变化直接改变 canonical sample 本体
- 后续若要重做切窗、生成 mask 或改任务定义，需要回头重解 `.bin`

### 3. 把 parser/debug/audit 信息一起打进 canonical `.npz`

当前没有采用。

原因：

- 会让 `.npz` 变胖
- 容易把机器学习样本和调试归档混成一类文件
- 这类信息当前不是训练默认消费所必需

### 4. 在 `v1` 中强制加入 `relative_time_s`

当前没有采用。

原因：

- 现有持久化链路还不能完美恢复真实每帧秒偏移
- 用近似时间冒充真实时间，会污染 canonical contract

## Consequences

该决策带来的直接影响：

- 机器学习侧可以把 `rd.npz` 当作唯一默认入口
- capture 侧仍可继续以 `raw_uart.bin` 保持原始真源
- canonical `.npz` 会更轻、更聚焦训练与数据集消费
- debug / audit / replay 信息不会和训练输入文件耦合在一起
- 若后续真的需要高精度帧级时间定位，需要单独推进新的采集或 sidecar 方案

同时也固定了一个边界：

- canonical `.npz` 不是“把当前所有能想到的字段都装进去”
- 而是“只保留主数据和训练不可缺的非推导信息”

## Next Actions

1. 在实现阶段为 `rd.npz v1` 明确每个字段的 shape、dtype 与缺失值约定。
2. 新增从 `raw_uart.bin + manifest/take` 导出单样本 `rd.npz` 的 extractor 路线。
3. 让后续 training / eval loader 默认只消费 `.npz`。
4. 若未来确认需要精确帧级时间标签，再单独讨论 `relative_time_s` 的采集与持久化方案。
5. 若未来 session contract 引入 `subject_id`，再评估 `.npz` schema 的升级路径。

## Verification / Open Questions

已确认：

- 当前 `raw_uart.bin` 是由完整原始字节直接落盘得到
- 当前 packet replay 能稳定恢复帧顺序、`frame_number` 与 `time_cpu_cycles`
- 当前 manifest 已稳定记录 `capture_window`、`target_window` 与 `marked_window`
- 当前 `.bin` 持久化链路尚未稳定记录每帧相对 `capture_window.start` 的真实秒偏移

仍待实现阶段继续明确的点：

- `rd` 的具体表示形式、shape 与 dtype
- `marked_window_s` 在缺失时的统一编码方式
- `schema_version` 的实际命名
- `subject_name` 是否在未来升级为 `subject_id`
