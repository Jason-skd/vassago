# Companion Profile 与 Background Session 规划

## Meta

- Date: 2026-04-20
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
  - `configs/collection/rd/global.toml`
  - `configs/collection/rd/profiles/*.toml`
  - `configs/registry/catalog_roots.toml`
  - `src/vassago/configs/models.py`
  - `src/vassago/collection/rd/config.py`
  - `src/vassago/collection/rd/cli.py`
  - `src/vassago/collection/rd/session.py`
  - `src/vassago/collection/rd/capture.py`
  - `src/vassago/collection/rd/qc_contract.py`
  - `docs/dev/context/20260411_capture_runtime_window_and_global_config_plan.md`
  - `docs/dev/context/20260412_capture_qc_boundary_and_manifest_public_contract.md`
  - `docs/dev/context/20260413_capture_manifest_runtime_selection_contract_refinement.md`
  - `docs/dev/context/20260413_capture_streaming_pipeline_and_global_dispatch_plan.md`

## Background

当前 RD collection 已经具备一条稳定的正样本采集主线：

- base profile 描述本轮手势采集意图
- operator 在 session 初始化时选择 profile、gesture、cfg、串口和默认字段
- live capture 以 `take` 为单位运行
- 每个 accepted take 落一份 `raw_uart.bin`
- `quick_qc` 以 `marked_window` 为 gate

但在后续讨论中，用户进一步明确了新的背景数据采集需求：

- 背景采集不应与手势采集复用同一个 session
- 背景采集也不应复制出一整套平行 base profile
- 应新增独立的 companion profile，用于描述背景采集策略
- 绑定方向应是 `base profile -> companion profile`
- operator 在选择完 base profile 和 mmWave cfg 后，应再选择本次采集类型：
  - `gesture`
  - `normal_activity`
  - `white_space`
- `normal_activity` 的目标样本量通常为正样本的 3 倍
- `white_space` 的目标样本量通常为正样本的 2 倍
- 背景采集不走逐 take 工作流，而是做长时间连续采集
- 连续采集期间的原始数据应尽可能全量保留
- 训练或后处理真正使用的 5 秒片段，应在采集后再随机选出

近期进一步收敛了一个实现取舍，用于降低中间层转换与 QC 复杂度：

- 背景采集的“采后随机切片”阶段，可以**直接产出下游可用的 `rd.npz`**（而不是先切成与手势采集同构的 `raw_uart.bin` 再转 npz）
- 背景样本质量与切片正确性应由**特化的 offline QC** 覆盖，不再要求复用 live `quick_qc` 的 marked_window gate

同时，用户进一步收紧了一条配置约束：

- companion profile 不应新增 `segment_duration_s = 5.0` 之类字段
- 背景切片时长应直接依赖现有 RD global baseline 中的 `capture_window_duration_s`
- 当前来源即 `configs/collection/rd/global.toml`

因此需要新增一份 context，固定：

- companion profile 的角色与绑定方向
- 背景采集的计划推导公式
- 背景采集与手势采集的 session contract 分流
- “不在 companion 中重复声明窗口时长”的设计边界

## Decision / Findings

### 1. companion profile 独立成新的 config kind，由 base profile 选择使用

当前正式决定：

- 新增独立的 managed config kind：
  - `collection_rd_companion_profile`
- companion profile 作为 `configs/` 树中的一等配置存在
- companion profile 不再反向声明“我绑定哪个 base profile”
- 绑定方向固定为：
  - `base profile -> companion profile`

也就是说：

- base profile 负责声明“这轮正样本默认配哪份 companion profile”
- companion profile 只表达背景采集策略本身
- companion profile 可以被多个 base profile 复用

当前不采用的关系方向是：

- `companion profile -> profile_config_id`

因为这种反向依赖会让 companion 失去复用性，并把配置关系变成“背景策略主动追认某个 base profile”，语义上不合适。

### 2. base profile 应显式声明默认 companion profile

当前正式决定：

- base profile schema 需要扩展 companion 相关字段
- 至少需要有：
  - `default_companion_profile_id`

是否额外支持：

- `allowed_companion_profile_ids`

当前可以作为实现阶段的可选增强项，但不是这次决策的核心。

本轮先固定的主语义是：

- 一个 base profile 应能直接声明默认使用哪份 companion profile
- operator 选定 base profile 后，背景采集策略默认随之确定

因此 session 初始化流程里：

1. 先选 base profile
2. 再选 mmWave cfg
3. 再选 `collection_type`
4. 若为背景采集类型，则从 base profile 解析默认 companion profile

### 3. `collection_type` 成为 session 初始化时的显式选择项

当前正式决定：

- `collection_type` 进入 session 初始化交互
- 合法值固定为：
  - `gesture`
  - `normal_activity`
  - `white_space`

其语义分工固定为：

- `gesture`
  - 沿用当前逐 take、带 `marked_window` 的 live capture 工作流
- `normal_activity`
  - 连续背景采集
  - 现场允许正常人类活动，但不应包含目标手势采集意图
- `white_space`
  - 连续底噪采集
  - 场景应尽量保持无人或无目标活动

这意味着：

- 当前 `init-session` 里“选完 profile 后立刻选 gesture”的顺序需要重排
- `gesture` 不再是所有 session 的第一分叉
- session contract 需要首先识别 `collection_type`

### 4. companion profile 不新增 `segment_duration_s`，背景片段时长直接继承 RD global baseline

当前正式决定：

- companion profile 不新增独立的 `segment_duration_s`
- companion profile 也不新增另一个与 5 秒切片等价的运行时窗口字段
- 背景采集后续切片所使用的单位时长，直接复用 RD collection global baseline 的：
  - `capture_window_duration_s`

当前来源为：

- `configs/collection/rd/global.toml`

这样做的原因是：

- 背景切片时长本质上不是一条新的 companion 级配置
- 它应和正样本的采集窗口长度保持同一仓库级基线
- 避免把“5 秒”在 `global.toml` 与 companion TOML 中重复声明两遍
- 减少以后窗口长度调整时的多处同步成本

当前进一步固定：

- companion profile 只表达背景采集策略
- 不表达 background-specific 的窗口长度

### 5. 背景采集量通过“样本配比 + 录制时长倍率”两层推导

当前正式决定：

- companion profile 中按模式定义样本配比：
  - `normal_activity.sample_ratio`
  - `white_space.sample_ratio`
- companion profile 中再定义：
  - `default_recording_duration_multiplier`

这两个量语义不同，不能混成一个字段：

- `sample_ratio`
  - 表达最终希望保留下来的背景样本量，是正样本 batch 的几倍
- `default_recording_duration_multiplier`
  - 表达为了给随机切片留冗余，连续录制时长再额外放大的倍数

当前正式固定以下推导口径：

- `base_batch_size = base_profile.batch_size`
- `window_duration_s = resolved_global.capture_window_duration_s`
- `target_segment_count = ceil(base_batch_size * sample_ratio)`
- `planned_recording_duration_s = target_segment_count * window_duration_s * default_recording_duration_multiplier`

例如：

- base profile 计划 `80` 个正样本
- `white_space.sample_ratio = 2`
- `default_recording_duration_multiplier = 1.25`
- `window_duration_s = 5.0`

则：

- `target_segment_count = 160`
- `planned_recording_duration_s = 160 * 5.0 * 1.25 = 1000s`

### 6. 背景采集走“全量保留连续原始数据，采后随机切片”的策略

当前正式决定：

- 背景采集不在 live 采集阶段直接挑出最终样本
- 背景采集期间应尽可能全量保留原始 UART 数据
- 真正用于训练或下游处理的 5 秒片段，在采集结束后再随机选出

对应策略固定为：

- live 阶段：
  - 录完整段连续原始数据
  - 不在现场做逐 5 秒 accept/reject
- post-processing 阶段：
  - 从完整连续数据中随机选取指定数量的 5 秒窗口
  - 形成最终背景样本清单

补充收敛（实现选择）：

- 背景切片产物优先直接输出为 `rd.npz`（以及一份可复现的切片 index/manifest）
- 仍应保留连续原始数据（`background_raw_uart.bin`），以支持复核、重切片与策略迭代

这意味着：

- 当前 `take` 模型不适合直接承载背景采集
- 背景采集不能只是“把现有 take loop 改成更长时间”
- 背景数据的样本选择与原始数据保留要分成两个阶段

### 7. 背景 runtime 必须改为边录边落盘，而不是沿用内存累积整段 raw_capture

当前正式决定：

- 背景连续采集不能沿用当前 per-take 的 `raw_capture: bytearray` 方案
- 新 runtime 必须改成流式写盘

这样做的原因是：

- 连续录制时长可能远大于单次 5 秒 take
- 若仍先把整段原始数据攒在内存里，再在结束后一次性写盘：
  - 内存占用会持续增长
  - 中途中断会导致整段数据丢失
  - 不利于恢复和分块校验

因此背景 runtime 的长期方向固定为：

- 串口读到的 `chunk` 直接进入持久化 writer
- 原始数据按连续时间顺序写入磁盘
- 必要时可进一步按 chunk / block 分段持久化
- manifest 中记录这段连续采集的持续时长、路径与后续切片计划

### 8. session contract 需要分成 `gesture` 与 `background` 两类策略

当前正式决定：

- session manifest 不再默认假设所有 session 都有 `takes`
- 当前 `gesture` session 与 `background` session 的 contract 需要显式分流

当前固定的高层分法为：

- `gesture` session
  - 保留当前 `takes` 列表与 per-take contract
  - 保留 `capture_window / target_window / marked_window`
- `background` session
  - 不再以 `takes` 作为 live 采集主骨架
  - 改为一段连续采集记录 + 一份背景切片计划

这里的 `background` 是运行时策略类目，当前包含：

- `normal_activity`
- `white_space`

当前不采用的方向是：

- 强行把 `normal_activity` / `white_space` 伪装成普通 `take` 列表

因为这会让：

- QC 契约
- UI 提示
- runtime 组织方式
- 后续切片计划

全部继续被手势工作流绑架。

### 9. 背景 session 初始化时，应把派生计划显式写进 manifest

当前正式决定：

- 背景采集的派生计划不是“运行时临时算一下就忘”
- 它应在 session 初始化时显式落入 manifest

当前至少需要落盘的派生字段包括：

- `collection_type`
- `companion_profile_id`
- `source_profile_config_id`
- `background_plan.sample_ratio`
- `background_plan.default_recording_duration_multiplier`
- `background_plan.window_duration_s`
- `background_plan.target_segment_count`
- `background_plan.planned_recording_duration_s`
- `background_plan.selection_policy`
- `background_plan.save_policy`
- `background_plan.selection_seed`

其中：

- `window_duration_s`
  - 是 session 里的派生结果
  - 允许写入 manifest 以便后续工具直接消费
  - 但它不是 companion profile 里的独立配置字段

当前正式固定的策略值包括：

- `selection_policy = "random_after_capture"`
- `save_policy = "keep_full_capture"`

### 10. 背景 session 的随机切片计划需要可复现，而不是每次后处理重新摇号

当前正式决定：

- 背景切片虽然是“采后随机选出”
- 但随机性必须可复现

因此后续实现中：

- session manifest 或其派生产物中应记录 selection seed
- 最终被选中的窗口范围也应形成显式记录

进一步固定（直接 npz 产物）：

- 采后切片应生成一份**切片 index/manifest**，至少记录：
  - source 连续原始数据路径（例如 `background/background_raw_uart.bin`）
  - `window_duration_s`
  - `target_segment_count`
  - `selection_seed`
  - 每个切片的窗口范围（例如 `start_s/end_s` 或窗口序号）与对应的 `rd.npz` 路径
- offline QC 应以该 index/manifest 作为主要对照物，校验可复现性与产物完整性

这意味着：

- “随机”是一次受控选择过程
- 不是每次训练前都临时重切一遍

### 11. 背景采集默认依附于 base profile 的 cfg 与全局基线，不再另起一套平行配置体系

当前正式决定：

- background session 仍从 base profile 出发
- 仍复用 base profile 的默认 cfg 与相关仓库级 baseline
- companion profile 只增加背景采集相关策略，不复制正样本 profile 的已有字段

因此：

- companion profile 不重写：
  - `gestures`
  - `environments`
  - `firmware_config_id`
  - `serial`
  - `capture_window_duration_s`
- 这些字段的主权继续留在 base profile 与 global baseline

## Alternatives Considered

### 1. 让 companion profile 反向绑定 `profile_config_id`

当前没有采用。

原因：

- 关系方向错误
- companion profile 会失去复用性
- 多个 base profile 共用一套背景采集策略会变得别扭

### 2. 在 companion profile 中新增 `segment_duration_s = 5.0`

当前没有采用。

原因：

- 该字段与现有 `global.toml` 中的 `capture_window_duration_s` 语义重复
- 会把仓库级采集窗口长度拆成两份配置源
- 未来修改窗口长度时需要多处同步

### 3. 在背景采集时直接随机抽样，只保存最终选中的 5 秒片段

当前没有采用。

原因：

- 会丢失大量原始数据
- 后续无法重新切片或复核
- 不利于更改随机策略、筛选策略和下游样本口径

### 4. 把 `normal_activity` / `white_space` 继续包装成普通 take workflow

当前没有采用。

原因：

- 与连续采集语义不符
- 会继续强依赖 `marked_window`
- 会让背景采集被当前 take/QC/UI 契约强行塑形

### 5. 让 operator 单独选择 companion profile

当前没有采用为默认路径。

原因：

- 用户当前要求是由 base profile 选择要使用的 companion profile
- companion 不是与 base profile 平级的主入口
- 默认 companion 跟随 base profile，更符合“外挂策略”定位

## Consequences

- `configs/` 管理层需要新增一种 companion profile config kind
- base profile schema 需要扩展 companion 绑定字段
- `init-session` 的交互顺序需要调整为：
  - profile
  - cfg
  - collection_type
  - gesture 或 background branch
- session schema 将从“统一 take contract”扩展为“gesture/background 两类 runtime contract”
- background runtime 需要新增连续采集与流式写盘路径
- `quick_qc`、`metadata_qc`、offline replay 与后续切片工具都要认识 `collection_type`
- 背景切片时长的唯一配置源继续留在 `global.toml`
- companion profile 将保持轻量，只管理背景采集的倍数与策略，不管理基础运行时窗口
- 背景“采后切片”阶段可直接输出 `rd.npz`，并配套 index/manifest 与特化 offline QC

## Next Actions

1. 设计 `collection_rd_companion_profile` 的 header 与 TOML schema。
2. 扩展 base profile loader，使其能解析默认 companion profile 绑定。
3. 为 catalog roots 增加 companion profile 的发现入口。
4. 重构 `init-session`，把 `collection_type` 提升为显式交互分叉。
5. 设计 background session 的 manifest schema，包括：
   - `collection_type`
   - `companion_profile_id`
   - `background_plan.*`
   - 连续原始数据路径与状态字段
6. 设计 continuous background capture runtime，改为边录边落盘。
7. 设计并实现采后随机切片 contract（推荐直接产出 `rd.npz`），包括：
   - selection seed
   - selected window records（index/manifest）
   - 产物路径（`rd.npz`）与可复现校验口径
8. 为背景切片新增特化 offline QC（面向 index/manifest 与 `rd.npz` 合法性/完整性）。

## Verification / Open Questions

已确认：

- companion profile 应独立成新的 config kind
- 绑定方向应为 `base profile -> companion profile`
- `segment_duration_s` 不应进入 companion profile
- 背景切片时长应复用 `global.toml` 中的 `capture_window_duration_s`
- 背景采集应采用“全量连续保存，采后随机切片”的模式
- 背景采集计划需要在 session 初始化时派生并写入 manifest

尚未确认：

- background session 是否沿用当前 manifest 文件名与目录骨架，还是引入独立子目录层
- base profile 是否只保留 `default_companion_profile_id`，还是同时支持 `allowed_companion_profile_ids`
- background session 的顶层 `gesture` 字段是否继续承担训练标签角色，还是引入更明确的 background label 字段
- continuous raw 数据最终是单文件落盘还是按 block/chunk 分段落盘
- 背景切片 index/manifest 的具体文件名与目录落位（是否作为 derived artifact 单独目录）
- 背景切片 offline QC 的最小必需字段集合（npz schema 与统计口径的下限）
