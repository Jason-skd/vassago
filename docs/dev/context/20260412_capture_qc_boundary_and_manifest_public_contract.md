# QC 边界与 Manifest 公共契约

## Meta

- Date: 2026-04-12
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
  - `src/vassago/collection/rd/qc_contract.py`
  - `src/vassago/collection/rd/quick_qc.py`
  - `src/vassago/collection/rd/session.py`
  - `src/vassago/collection/rd/capture.py`
  - `src/vassago/collection/rd/config.py`
  - `.lefthook.yaml`
  - `tests/test_collection_quick_qc.py`

## Background

当前仓库已经有最小可用的 live `quick_qc`，但 `offline_qc` 仍未落地。

同一轮讨论中，进一步明确了两件事：

- `quick_qc` 与 `metadata_qc` 在 `offline_qc` 中应是同等级、可插拔的 peer checks
- 后续 `raw_uart.bin -> rd.npz` 处理链不应依赖 `config_snapshot` 才能理解 manifest 的公共字段

这直接引出一个新的 manifest 契约要求：

- manifest 顶层需要成为 downstream tooling 的公共 contract
- `config_snapshot` 需要成为完整、稳定的 config provenance snapshot

在这个前提下，`offline_qc` 的职责不再只是“读 snapshot 做校验”，而是：

- 维护顶层公共 contract 的完整性
- 维护顶层 contract 与 snapshot 之间的合规关系
- 复用 live `quick_qc` 的样本质量口径

## Decision / Findings

### 1. `offline_qc` 是 orchestrator，不是单一检查器

后续 `offline_qc` 的角色固定为 runner / orchestrator。

它负责：

- 组装 session-level context
- 顺序执行一组 peer QC plugins
- 汇总 findings
- 用统一 severity 决定 CLI 退出结果
- 为 `lefthook` 提供可脚本化入口

它不负责把所有规则都塞进一个文件。

当前明确的 peer plugins 至少包括：

- `quick_qc`
- `metadata_qc`
- 未来的 `ai_precheck_qc`

### 2. live collection 只接入 `quick_qc`

当前 collection live 流只直接运行 `quick_qc`。

边界固定为：

- `quick_qc`
  - 只检查样本采集质量
  - 使用运行时内存态输入
  - 在 live collection 中作为 accept/reject gate
- `metadata_qc`
  - 不进入 live operator gate
  - 仅属于 `offline_qc` runner 的 session-level checks

### 3. manifest 顶层是 downstream public contract

manifest 顶层不再只是“当前 session 的随手 metadata”。

当前正式定义为：

- 顶层字段应支持 downstream tooling 直接消费
- `raw_uart.bin -> rd.npz` 路线不得要求先理解 `config_snapshot`
- `offline_qc` 负责维护这条公共 contract 不断

这意味着：

- downstream tooling 应优先读取 manifest 顶层和 take 顶层字段
- `config_snapshot` 不是 extractor-facing contract
- 若 extractor 需要某字段，则该字段必须在 manifest 顶层稳定暴露

### 4. `config_snapshot` 负责一比一复制生效 config

`config_snapshot` 的契约固定为：

- 尽可能完整复制本次 session 初始化时的生效 config
- 作为 provenance baseline 存在
- 作为 `offline_qc` 的对照基准存在
- 不再承担“给 downstream tooling 直接提供公共字段”的职责

这一层与顶层的分工不同：

- 顶层：公共 contract
- snapshot：完整 config 镜像

### 5. config 对 manifest 成型的三种作用，决定字段复制策略

当前把 profile/global config 对 manifest 的作用拆成三类：

1. 提供默认值
2. 提供可选列表
3. 提供写死的数据

对应规则固定为：

- 若某字段属于“默认值作用产出的实际 session 字段”，它必须稳定出现在 manifest 顶层
- 若某字段属于“可选列表作用产出的公共字段”，它必须稳定出现在 manifest 顶层
- 若某字段属于“写死的数据”，并且 downstream tooling 需要直接消费，它也必须稳定出现在 manifest 顶层
- 同时，以上字段仍应在 `config_snapshot` 中保留完整来源

### 6. 当前明确需要进入顶层公共 contract 的字段

当前至少固定以下 top-level public contract：

- `schema_version`
- `session_id`
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
- `batch_size`
- `gesture_options`
- `environment_options`
- `cli_port`
- `data_port`
- `data_baudrate`
- `takes`

当前至少固定以下 take-level public contract：

- `take_index`
- `take_id`
- `status`
- `raw_uart_path`
- `accepted_at`
- `capture_window`
- `target_window`
- `marked_window`

说明：

- `batch_size`
  属于 config 写死数据，但 downstream tooling 需要直接消费，因此必须顶层声明，同时也必须进入 snapshot。
- `gesture_options`
  属于 config 的可选列表，因此必须顶层声明，同时也必须在 snapshot 里保留其 config 来源。
- `environment_options`
  同上。

### 7. 当前明确需要进入 `config_snapshot` 的字段

`config_snapshot` 当前应按“完整 config 镜像”方向收敛，至少应保留：

- `schema_version`
- `config_id`
- `label`
- `description`
- `batch_size`
- `global.config_id`
- `firmware.config_id`
- `runtime.*`
- `defaults.*`
- `serial.*`
- `options.*`
- `gesture_target_durations`

这里的目标不是“只保留恢复时最少够用的字段”，而是“让 snapshot 真正成为 config provenance baseline”。

### 8. 顶层字段与 snapshot 的合规关系

当前固定以下 severity 口径：

- 顶层公共 contract 自身缺失、类型错误、值域非法
  - `ERROR`
- 顶层固定镜像字段与 snapshot 对应字段不一致
  - `ERROR`
- 顶层实际选择字段不属于 snapshot 提供的 allowed options
  - `ERROR`
- 顶层实际选择字段与 snapshot default 不一致，但仍然合法
  - `WARN`

当前明确的镜像关系包括：

- `batch_size <-> config_snapshot.batch_size`
  - `ERROR`
- `gesture_options <-> config_snapshot.options.gestures`
  - `ERROR`
- `environment_options <-> config_snapshot.options.environments`
  - `ERROR`

当前明确的 default 对照关系包括：

- `hand <-> config_snapshot.defaults.hand`
  - `WARN`
- `distance_m <-> config_snapshot.defaults.distance_m`
  - `WARN`
- `angle_deg <-> config_snapshot.defaults.angle_deg`
  - `WARN`
- `environment <-> config_snapshot.defaults.environment`
  - `WARN`
- `radar_id <-> config_snapshot.defaults.radar_id`
  - `WARN`
- `firmware_id <-> config_snapshot.defaults.firmware_id`
  - `WARN`
- `data_baudrate <-> config_snapshot.serial.data_baudrate`
  - `WARN`

当前明确的 membership 对照关系包括：

- `gesture in config_snapshot.options.gestures`
  - `ERROR`
- `environment in config_snapshot.options.environments`
  - `ERROR`

### 9. `.cfg` 继续采用 `config_id`-only 持久化

目前不要求把 mmWave `.cfg` 本体快照进 manifest。

当前继续采用非对称设计：

- collection profile
  - `snapshot-complete`
- mmWave `.cfg`
  - `config_id`-only

这项设计成立的前提被固定为：

- 同一个 mmWave `config_id` 的内容视为不可变
- `.cfg` 允许迁移和重命名
- `.cfg` 不允许在不变更 `config_id` 的前提下静默改内容

### 10. 两处 `schema_version` 的语义不同

当前明确：

- manifest 顶层 `schema_version`
  - 表示 session manifest 自己的 schema 版本
- `config_snapshot.schema_version`
  - 表示 snapshot 对象自己的 schema 版本

它们不是同一个东西，也不等于 profile TOML 正文里的 `schema_version`。

## Alternatives Considered

### 1. 只保留 `config_snapshot`，让 downstream tooling 也去读 snapshot

当前没有采用。

原因：

- downstream tooling 会被迫理解 snapshot schema
- `raw_uart.bin -> rd.npz` 的公共 contract 会变得不稳定
- `offline_qc` 难以明确“顶层 contract 是否断掉”

### 2. 顶层只保留实际选择值，不复制 option lists

当前没有采用。

原因：

- 只保留实际值不足以表达公共 contract 的有效选择边界
- 未来 extractor 或更轻量 tooling 仍可能被迫回退到 snapshot
- `offline_qc` 难以在不读 snapshot 业务逻辑的前提下维护 allowed-set contract

### 3. 对 collection profile 也只保留 `config_id`

当前没有采用。

原因：

- 这会削弱历史 session 的 provenance 和离线可校验性
- 不符合“snapshot 完整镜像生效 config”的目标
- 会让 metadata/QC 再次依赖当前仓库里的 TOML 仍然未漂移

## Consequences

该决策带来的直接影响：

- `offline_qc` 需要维护两层契约，而不是只维护 snapshot
- manifest schema 将继续保留“顶层公共 contract + snapshot baseline”双层结构
- `batch_size`、`gesture_options`、`environment_options` 这类字段将进入双写校验口径
- future extractor 可只依赖 manifest 顶层 contract，不必理解 snapshot
- `quick_qc` 和 `metadata_qc` 的接口需要共享统一 finding/report 模型
- 现有写死 repo profile 值的测试需要改成 stub-config 或结构性断言

## Next Actions

1. 将当前 context 作为 `quick_qc` / `offline_qc` 并行开发的边界基准。
2. 在 `src/vassago/collection/rd/qc_contract.py` 中固定共享 finding/report/check interfaces。
3. 让 `quick_qc` 改为底层产出 peer-style report，同时保留当前 live `QuickQcDecision` 兼容层。
4. 为 `metadata_qc` 实现 manifest top-level contract 校验。
5. 为 `offline_qc` 实现 runner 和 CLI 入口。
6. 将 `offline_qc` 命令接入 `.lefthook.yaml`。
7. 调整 manifest 写入逻辑，使 `gesture_options`、`environment_options`、`batch_size` 满足当前契约。
8. 将 collection 测试从“写死 repo sample config 的具体值”改为 stub-config 和结构性断言。

## Verification / Open Questions

已确认：

- 当前 live collection 已有最小 `quick_qc`
- 当前 `offline_qc` 尚未实现
- 当前 manifest 已保留 `config_snapshot`
- 当前 `batch_size` 仍只在顶层，尚未进入 snapshot
- 当前 manifest 顶层尚未写入 `gesture_options` / `environment_options`
- 当前测试中存在写死 repo sample config 值的失败用例

仍需在实现阶段继续完成的点：

- 是否为顶层公共 contract 单独引入更明确的 schema 命名
- `offline_qc` 在 `lefthook` 中采用 `pre-commit` 还是 `pre-push`
- `extract-to-npz` 最终最小必需字段集合是否还需要再裁一轮
