# Collection Manifest 顶层与 Snapshot 分工收紧

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
  - `docs/dev/context/20260412_capture_qc_boundary_and_manifest_public_contract.md`
  - `src/vassago/collection/rd/session.py`
  - `src/vassago/collection/rd/capture.py`
  - `src/vassago/collection/rd/qc_contract.py`
  - `src/vassago/collection/rd/metadata_qc.py`
  - `src/vassago/collection/rd/ui.py`
  - `tests/test_collection_session.py`
  - `tests/test_collection_cli.py`
  - `tests/test_collection_offline_qc.py`
  - `tests/test_collection_quick_qc.py`

## Background

`20260412_capture_qc_boundary_and_manifest_public_contract.md` 已经把
manifest 分成了两层：

- manifest 顶层：downstream public contract
- `config_snapshot`：完整 provenance baseline

但在后续实现中，顶层仍残留了两个不符合当前口径的字段：

- 顶层 `config_id`
  - 实际表达的是 collection profile id
  - 名称过于模糊，容易被误读成“本次 session 实际使用的 mmWave cfg id”
- 顶层 `batch_size`
  - 属于 profile 写死值
  - 不符合“顶层字段应表达运行时实际 session 选择结果或 extractor-facing 直接字段”的收紧口径

同时，默认 firmware cfg 绑定和运行时实际选择结果一度被混在同一个
snapshot 字段语义里，导致：

- public contract 没有直接暴露“这次 session 实际用了哪份 cfg”
- `config_id` 这个名称在顶层产生误导
- 顶层与 snapshot 的分工被写死字段和运行时选择字段混杂

## Decision / Findings

### 1. 顶层 public contract 进一步收紧为“运行时实际 session 字段”

当前进一步固定：

- TOML 只提供默认值、可选列表和固定 baseline
- 顶层 public contract 只暴露：
  - 运行时实际选择结果
  - downstream 直接消费的串口与 take 字段
  - manifest 自己的 session-level 元信息
- profile 写死字段不再因为“也许 downstream 会看”就默认进入顶层

这条 refinement 覆盖并收紧了 `20260412` 文档中
“写死字段如果 downstream 需要也可进入顶层”的宽口径。

### 2. `firmware_config_id` 必须进入 manifest 顶层

当前正式决定：

- `defaults.firmware_config_id`
  - 只是 session 初始化时的默认高亮值
- `firmware_config_id`
  - 才是本次 session 初始化后真正选中的 mmWave cfg id

因此：

- `firmware_config_id` 属于“默认值作用产出的实际 session 字段”
- 它必须稳定出现在 manifest 顶层
- profile 默认 cfg 必须保留在 snapshot 的 `defaults.firmware_config_id`

两者关系固定为：

- 顶层 `firmware_config_id`
  - downstream-facing runtime contract
- `config_snapshot.defaults.firmware_config_id`
  - profile default baseline
- 二者不同属于“实际选择值偏离默认值”
- 这类偏离应在 offline QC 中记为 `WARN`，而不是 `ERROR`

### 3. profile TOML 与 snapshot 都不再保留独立 `[firmware]` / `firmware.*` 分组

当前正式决定：

- profile TOML 不再使用独立 `[firmware]` 分组
- 默认 firmware cfg 统一收进 `[defaults].firmware_config_id`
- `config_snapshot` 也不再使用 `firmware.config_id`
- 默认 firmware cfg 统一收进 `config_snapshot.defaults.firmware_config_id`

这样做的原因是：

- 该字段表达的是默认值，不是单独一类运行时对象
- 放在 `defaults` 下能直接体现“它和 `hand`、`environment` 一样，都是 session 初始化默认项”
- `firmware.config_id` 这种命名会误导成“这里保存的是实际使用值”

### 4. 顶层 `config_id` 退出 public contract

当前正式决定：

- 顶层不再保留裸字段 `config_id`
- collection profile id 只保留在 `config_snapshot.config_id`

原因：

- 顶层 `config_id` 语义不清
- 它表达的是 profile identity，不是运行时选择结果
- 它会与 `firmware_config_id` 的语义竞争，制造误读

若界面或工具需要展示 profile id，应明确命名为：

- `profile_config_id`

并从 `config_snapshot.config_id` 读取，而不是重新引入裸 `config_id`。

### 5. 顶层 `batch_size` 退出 public contract

当前正式决定：

- 顶层不再保留 `batch_size`
- `batch_size` 继续保留在 `config_snapshot.batch_size`
- manifest 实际 take 计划由 `takes` 列表本身表达

对应约束改为：

- `len(takes)` 必须等于 `config_snapshot.batch_size`

这样做的原因是：

- `batch_size` 是 profile 写死值，不是运行时选择结果
- `takes` 已经完整表达本次 session 的计划骨架
- downstream 若关心计划总量，可直接读取 `len(takes)`

### 6. schema 与 QC 必须同步收口

本次 refinement 的直接实现要求是：

- session manifest schema 升级到 `collection_rd_session_v6`
- snapshot schema 升级到 `collection_rd_config_v5`
- manifest 写入逻辑新增顶层 `firmware_config_id`
- manifest 写入逻辑去除顶层 `config_id`
- manifest 写入逻辑去除顶层 `batch_size`
- metadata QC 新增：
  - `firmware_config_id <-> config_snapshot.defaults.firmware_config_id`
    - `WARN`
  - `len(takes) <-> config_snapshot.batch_size`
    - `ERROR`
- profile loader 不再接受旧 `[firmware]` 配置
- resume / UI 不再接受旧 snapshot `firmware.config_id`

## Alternatives Considered

### 1. 继续把实际 cfg 只放在 snapshot

当前没有采用。

原因：

- `defaults.firmware_config_id` 只是默认值，不是实际选择结果
- snapshot-only 会让顶层 public contract缺少关键 runtime 选择字段
- 容易让顶层 `config_id` 被误认为“就是本次 cfg”

### 2. 保留顶层 `config_id`，仅新增顶层 `firmware_config_id`

当前没有采用。

原因：

- 这只会把歧义从一个字段变成两个近似字段
- 顶层 `config_id` 仍然不符合当前更严格的字段复制策略

### 3. 保留顶层 `batch_size`

当前没有采用。

原因：

- 它属于 profile 固定值，不是运行时实际 session 字段
- `takes` 列表已经能表达计划总量
- `config_snapshot.batch_size` 已足够承担 provenance 角色

## Consequences

- 新 manifest 的顶层 contract 更接近“session 实际运行结果与下游直接消费字段”
- snapshot 与顶层分工更清晰：
  - 顶层：实际选择结果与直接消费字段
  - snapshot：固定 baseline 与 provenance
- 默认 firmware cfg 的归属也更清晰：
  - profile TOML：`defaults.firmware_config_id`
  - snapshot：`defaults.firmware_config_id`
  - top-level：`firmware_config_id`
- UI、QC 和测试都必须避免再把 profile id 裸暴露为 `config_id`
- 当前仍处于开发调试阶段，manifest / profile schema 不为旧结构提供兼容路径

## Next Actions

1. 若后续还有新的 top-level 字段诉求，先判断它是：
   - 默认值产出的实际 session 字段
   - 可选列表产出的公共字段
   - 还是 profile 固定 baseline
2. 只有前两类，才优先考虑进入顶层 public contract。
3. 若某字段只是 provenance 或 profile identity，应优先留在 snapshot。
