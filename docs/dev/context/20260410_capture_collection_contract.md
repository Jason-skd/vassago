# Collection 契约与预配置边界

## Meta

- Date: 2026-04-10
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
  - `docs/dev/context/20260410_repo_tonight_execution_plan.md`
  - `src/vassago/cli.py`
  - `src/vassago/firmware/mmwave/cli.py`
  - `src/vassago/firmware/mmwave/config.py`
  - `pyproject.toml`
  - `../vassago.bak/src/vassago/collection/rd/session.py`
  - `../vassago.bak/src/vassago/collection/rd/capture.py`
  - `../vassago.bak/src/vassago/collection/rd/quality.py`
  - `configs/rd_phase1_uart.cfg`
  - `configs/profile_3d.cfg`
  - `configs/collection/rd/*.toml`
  - `src/vassago/collection/rd/session.py`
  - `src/vassago/collection/rd/config.py`
  - `src/vassago/collection/rd/cli.py`

## Background

`20260410_repo_tonight_execution_plan.md` 已经明确今晚主线顺序为：

1. 先完成 `smoke_test`
2. 再落 `collection`
3. 然后落 `QC`

同一轮讨论中，还提前固定了新版 `collection` 不再沿用 `.bak` 的
`fixed_window_v1` 契约，而是从第一版就支持三窗口语义，并且要求：

- `collection` 有独立命令树和状态机
- `gesture`、`speed`、`environment` 等关键项不再靠自由手输
- `collection` 需要一个由 dev 预先维护的配置入口
- 这类“本轮采集配置”会在后续被反复覆盖，因此运行时生效配置必须完整复制到 manifest

随后又对旧版 `.bak` manifest 的 metadata 做了逐项讨论，目的是把第一版
`collection` 契约压缩到“状态机必需字段 + 数据定位字段 + 采集窗口字段”，
避免把自由标签和审计字段过早固化。

## Decision / Findings

### 1. 新版 `collection` 采用独立 context，不再继续混入 repo 总执行计划

`20260410_repo_tonight_execution_plan.md` 保留“总顺序和依赖边界”的角色。

`collection` 本身的数据契约、预配置入口、metadata 剪枝和 manifest 原则，
在本文件中单独固定，供后续实现与评审引用。

### 2. 顶层命令树采用 `collection`

新版命令主域采用 `collection`，不采用 `capture`。

原因：

- 当前讨论主语一直围绕 `collection`
- 它和 session、operator workflow、QC 的关系更直接
- 可以避免和底层“capture one window”动作命名混淆

### 3. 三窗口字段直接使用英文语义

新版 `collection` 不再保留中文语义映射，窗口字段直接采用：

- `capture_window`
- `target_window`
- `marked_window`

其语义固定为：

- `capture_window`
  - 固定 5 秒
  - 覆盖动作前后背景
- `target_window`
  - 由 `gesture + speed` 在预配置中提前定义
  - 表示理想执行区间
- `marked_window`
  - 由 operator 在采集时键盘打点生成
  - 表示本次真实动作区间

### 4. 窗口坐标统一采用相对当前 5 秒采集起点的秒偏移

窗口字段统一保存为相对本次 `capture_window` 起点的秒偏移，而不是绝对时间戳。

推荐结构：

```json
{
  "start_s": 1.2,
  "end_s": 2.7
}
```

约束：

- `capture_window` 固定为 `{ "start_s": 0.0, "end_s": 5.0 }`
- `target_window` 由预配置给出
- `marked_window` 只有在开始和结束都成功打点时才写入
- 若 operator 未完成一对打点，`marked_window` 记为 `null`

### 5. `subject_name` 是唯一的人员标识字段

新版 manifest 保留 `subject_name`，不再额外保留 `subject_id`。

约束前提：

- collaborator 负责输入稳定、一致的英文标识
- 第一版默认将其视为规范化 key，而不是展示昵称
- session 命名、目录命名、样本命名都可以直接基于该值生成

### 6. 需要保留的 metadata 范围已经收敛

第一版 `collection` manifest 应保留以下元信息：

- `subject_name`
- `hand`
- `distance_m`
- `angle_deg`
- `environment`
- `operator_name`
- `note`
- `radar_id`
- `firmware_id`
- `gesture`
- `speed`
- `config_id`
- `cli_port`
- `data_port`
- `data_baudrate`

其中字段约束为：

- `hand`
  - 保留
  - 后续可能用于分析准确率影响因素
- `distance_m`
  - 保留
  - 可空
- `angle_deg`
  - 保留
  - 可空
- `environment`
  - 保留
  - 不允许自由手输
  - 必须从 dev 预定义列表选择
- `operator_name`
  - 保留
  - 必填
- `note`
  - 保留一个即可
  - 可空
  - 不再保留 `session_tags` 这类自由标签集合
- `radar_id`
  - 保留
- `firmware_id`
  - 保留

### 7. `gesture` 和 `speed` 改为选择框，不再手动输入

由于第一版要求提前定义每个 `gesture + speed` 的 `target_window`，
因此 `gesture` 与 `speed` 都必须来自预配置列表，而不是运行时自由输入。

这会直接带来以下实现约束：

- `collection` 交互层必须提供选择框
- `gesture + speed` 的可选组合由配置驱动
- `target_window` 必须能从已选组合稳定解析出来

### 8. 需要一个由 dev 预先维护的 `collection` 配置入口

新版 `collection` 第一版必须引入一个显式的预配置入口，用于定义本轮采集的默认配置。

当前决定采用：

- 配置格式：TOML
- 推荐位置：`configs/collection/rd/*.toml`

选择 TOML 的原因：

- 可直接使用标准库 `tomllib`
- 不需要新增运行依赖
- 比 JSON 更适合人工维护
- 适合同时承载“默认项 + 枚举项 + `gesture/speed -> target_window` 映射”

该配置入口至少需要承载：

- 本轮可选的 `gesture`
- 本轮可选的 `speed`
- 本轮可选的 `environment`
- 默认 `hand`
- 默认 `distance_m`
- 默认 `angle_deg`
- 默认 `operator_name`
- 默认 `radar_id`
- 默认 `firmware_id`
- 绑定的 `config_id`
- 默认串口/波特率策略
- 每个 `gesture + speed` 对应的 `target_window`

### 9. 生效配置必须完整复制到 manifest

第一版 `collection` 不应只在 manifest 里写“配置文件路径”或“profile id”。

当前明确要求：

- 运行时真正生效的 `collection` 配置必须完整复制到 manifest
- manifest 中需要保存一份 config snapshot
- 后续即使外部 TOML 被覆盖，也不影响旧 session 的语义还原

这意味着：

- manifest 是一次 session 的完整语义快照
- session 恢复、QC 和后续数据分析都不应依赖外部配置文件仍然保持原状

### 10. 旧版 `.bak` metadata 中明确剪枝的字段

第一版不继续保留以下旧字段：

- `subject_id`
- `subject_name` 之外的第二人员主键
- `session_tags`
- `session_dir`
- `sample_dir_pattern`
- `accepted_take_count`
- `remaining_take_count`
- `sample_id`
- `sample_dir`
- `rejected_attempt_count`
- `last_attempt_started_at`
- `last_attempt_ended_at`
- `last_decision`
- `expected_frame_period_s`
- `expected_frame_count_per_take`
- `collector_version`
- `batch_runner_version`
- 旧版 `segmentation_mode = fixed_window_v1`

剪枝原因：

- 它们要么是派生字段
- 要么是审计字段
- 要么是旧版固定窗口语义残留
- 要么当前没有真实消费方

### 11. 第一版需要保留的状态骨架

即使做 metadata 剪枝，第一版 manifest 仍需要保留以下状态骨架：

- `schema_version`
- `session_id`
- `created_at`
- `updated_at`
- `session_status`
- `batch_size`
- `takes`

每个 take 最少保留：

- `take_index`
- `take_id`
- `status`
- `raw_uart_path`
- `accepted_at`
- `capture_window`
- `target_window`
- `marked_window`

### 12. session 恢复方式固定为“从未完成会话列表中选择”

新版 `collection` 不再把“手输 manifest 路径”作为默认恢复方式。

第一版交互方向固定为：

- 列出未完成 session
- operator 选择一个待恢复 session
- CLI 再进入该 session 的状态机

### 13. 当前 CLI 依赖边界已经足够支持该方案

虽然总执行计划曾把 `typer`、`questionary`、`rich` 记作待确认项，
但当前主仓库运行依赖实际上已经包含三者。

因此 `collection` 第一版不需要再围绕 CLI 依赖做额外决策，
应直接复用现有依赖边界推进实现。

## Alternatives Considered

### 1. 沿用 `.bak` 的 `fixed_window_v1` manifest

没有采用。

原因：

- 无法表达 `target_window`
- 无法表达 `marked_window`
- 会把旧版字段和新语义混在一起
- 后续仍要重做数据契约

### 2. 继续保留 `subject_id + subject_name` 双字段

没有采用。

原因：

- 当前阶段没有必要维护第二套人员主键
- 如果 collaborator 能保证输入一致英文标识，一个 `subject_name` 足够
- 双字段会放大同步成本和清洗成本

### 3. 让 `gesture`、`speed`、`environment` 保持自由输入

没有采用。

原因：

- `target_window` 依赖 `gesture + speed`
- 这些字段一旦自由输入，配置映射就会变脆弱
- 会把本应在开发期收口的约束重新推给 collaborator

### 4. 只在 manifest 里记录配置文件路径，不复制生效配置

没有采用。

原因：

- 这类配置未来会被反复覆盖
- 旧 session 会失去稳定语义
- 恢复、QC 与离线分析都会受外部文件漂移影响

### 5. 使用 JSON 或 Python schema 作为 `collection` 配置入口

当前没有采用。

原因：

- JSON 的人工维护体验较差
- Python schema 会把配置问题过早耦合进实现代码
- TOML 已经足够表达当前第一版结构

## Consequences

该决策会直接带来以下影响：

- `collection` 的实现起点不再是“复刻 `.bak`”，而是“围绕新契约重建”
- 实现前必须先定义 `collection` TOML 结构
- 交互层必须支持选择框，而不是依赖自由文本输入
- manifest 第一版会比旧版更聚焦于“快照 + 状态 + 三窗口”
- `QC` 后续会天然拥有消费窗口元信息的入口
- 当前阶段会推迟一些旧版审计字段和自由标签字段
- session 恢复和回放语义会更稳定，因为它不再依赖外部配置仍然未变

## Next Actions

1. 先定义 `collection` TOML 配置结构
2. 再定义 `collection` manifest v2 草案
3. 再实现 `collection` CLI 的交互式选择层
4. 再接入 5 秒采集、`marked_window` 打点和 session 恢复
5. 最后让 `QC` 开始消费窗口元信息

## Verification / Open Questions

已确认：

- 顶层命令采用 `collection`
- 配置入口采用 TOML
- 生效配置必须完整复制到 manifest
- 三窗口字段直接使用英文语义
- `capture_window` 固定 5 秒
- `marked_window` 不完整时记为 `null`
- `subject_name` 是唯一人员标识字段
- `gesture`、`speed`、`environment` 都改为预定义选择项
- `hand`、`distance_m`、`angle_deg`、`operator_name`、`note`、`radar_id`、`firmware_id` 的保留边界已经明确
- 旧版大量派生与审计字段已经明确不进入第一版

尚未确认：

- `collection` TOML 的最终字段命名细节
- `session_id`、样本目录名、样本文件名的最终格式
- `marked_window` 的具体键盘交互方式
- `collection` CLI 第一版是否同时提供完整非交互模式
