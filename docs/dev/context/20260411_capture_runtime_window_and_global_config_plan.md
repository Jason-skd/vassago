# Collection 运行时窗口与全局配置分层计划

## Meta

- Date: 2026-04-11
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
  - `docs/dev/context/20260410_capture_collection_contract.md`
  - `configs/collection/rd/*.toml`
  - `src/vassago/collection/rd/config.py`
  - `src/vassago/collection/rd/session.py`
  - `src/vassago/collection/rd/capture.py`
  - `src/vassago/collection/rd/cli.py`
  - `docs/collaborators/tutorials/rd_collection.md`

## Background

`20260410_capture_collection_contract.md` 固定了第一版 `collection` 的三窗口语义、
TOML 配置入口和 manifest snapshot 原则，但当前第一版实现仍保留了以下旧假设：

- `target_window` 在 session 初始化时按 `gesture + speed` 直接写死
- operator 需要在采集中手动打 `marked_window` 的开始和结束
- `capture_window` 虽然固定 5 秒，但仍作为显式 operator 语义存在
- `speed` 仍被当作显式输入字段

在实机交互中，用户进一步明确提出：

- operator 应只感知倒计时与 `GO`，不感知 `capture_window`
- `GO` 固定在 5 秒倒计时结束时
- `capture_window` 应在后台随机覆盖 `target_window`
- `target_window` 不再配置绝对起止，只配置时长
- `marked_window` 在 `GO` 自动开始，operator 只负责打结束点
- reject 应收口到 `quick QC`
- `speed` 可从 collection 输入契约中移除
- 配置分层的目标是“仓库复用”，而不是“单轮采集计划复用”

因此需要新增一份 context，记录相对于 2026-04-10 契约的运行时重构计划，
并明确哪些字段应提升为仓库级全局配置。

## Decision / Findings

### 1. `capture_window` 继续存在，但对 operator 完全隐藏

`capture_window` 仍保留为数据契约字段，且总时长固定为 5 秒。

但新的交互语义里：

- operator 不再被要求理解 `capture_window`
- operator 面对的是固定 5 秒倒计时
- `GO` 固定发生在倒计时结束时

新的随机性不再通过“随机 `GO`”表达，而是通过“后台随机放置 `capture_window`”
来保证 `target_window` 能落在合法区间内。

### 2. `target_window` 不再在配置或 session 初始化阶段写死起止时间

原方案中：

- `target_window` 由 `gesture + speed` 直接映射到 `{start_s, end_s}`

新方案中：

- 不再预配置 `target_window.start_s / end_s`
- 只预配置 `target_window_duration_s`
- 每次 attempt 运行时才生成本次实际的 `target_window`
- accepted take 仍必须把本次真实生成出来的 `target_window` 写入 manifest

因此，“不写死 `target_window`”的含义是：

- 不在 TOML 中写死起止
- 不在 session init 时为所有 takes 提前展开

而不是：

- 最终数据中不记录实际 `target_window`

### 3. `marked_window` 改为自动起点 + 人工终点

新的 `marked_window` 语义固定为：

- `marked_window.start_s = target_window.start_s`
- `marked_window.end_s = operator` 的结束打点时间

这意味着：

- operator 不再负责开始打点
- operator 只负责结束打点
- 若未在允许时限内完成结束打点，则 `quick QC` 负责 reject

因此 `marked_window` 不再是“纯人工窗口”，而是“系统起点 + 人工终点”的混合窗口。

### 4. reject 逻辑并入 `quick QC`

原本的“超时未结束就直接在采集状态机内 auto reject”思路，被进一步收口为：

- collection 负责组织一次 attempt 的运行时数据
- `quick QC` 负责统一裁决 accept / reject

第一版 `quick QC` 可以先做最小原型，只覆盖：

- 未收到结束打点
- 结束打点超过 `target_window + grace`
- `bytes_read == 0`
- `valid_packets == 0`

在 `QC` 主流程尚未完成前，可以先实现一个最小可用的 `quick QC` mock / prototype，
用于保证 collection 功能可验收，但不阻塞后续完整 QC 的设计。

### 5. reject 的 attempt 不进入正式样本集

当前计划固定为：

- rejected attempt 不保留为正式样本
- 不写入正式 `takeXX/raw_uart.bin`
- 不占用 accepted sample

也就是说，正式数据集只面向 accepted take。

### 6. `speed` 从 collection 输入契约中移除

当前倾向明确为：

- `speed` 不再作为采集时输入字段
- 本轮采集清单只围绕 `gesture` 定义
- 以后如需速度相关语义，应优先从 `marked_window` 或派生时长推断

这意味着 2026-04-10 契约中“`gesture + speed -> target_window` 映射”的部分，
将在后续实现中被新方案取代。

### 7. 配置分层的目标是“仓库复用”，不是“采集计划复用”

当前已明确：

- 全局配置的职责是提供仓库级 baseline
- 单轮 profile 的职责是表达本轮采集意图

因此不再优先追求“多层目录递归叠加的采集计划复用”，而是固定为：

- `configs/collection/rd/global.toml`
- 单轮采集 profile

两层即可。

### 8. 全局配置只承载真正稳定、底层、声明性的字段

全局配置不应用来承载每轮都会变化的业务逻辑。

当前打算提升为全局字段的内容如下：

- `capture_window_duration_s`
  - 默认 `5.0`
  - 仓库级 baseline
- `countdown_duration_s`
  - 默认 `5.0`
  - 对应固定 `GO` 倒计时
- `marked_window_end_grace_s`
  - 全局默认值
  - profile 允许覆盖
- `[serial]`
  - `cli_baudrate`
  - `data_baudrate`
- `end_mark_key`
  - 当前计划改为 `space`
- 其他几乎不动、只用于声明或展示的仓库级元信息

当前明确不提升为全局字段的内容如下：

- `gestures`
- `environments`
- `target_window_duration_s`
- `operator_name`
- `radar_id`
- `firmware_id`
- 本轮任何实验性、业务性采集清单

这些字段仍属于单轮 profile。

### 9. 配置覆盖允许发生，但由检查脚本发出 `WARN`

当前计划不是“禁止覆盖”，而是：

- 全局配置提供默认值
- profile 允许覆盖这些默认值
- 后续通过配置检查脚本给出 `WARN`

这样做的原因是：

- 仓库需要可复用
- 偶发临时调整需要留出口
- 但又不希望 override 变成无感行为

因此后续的 config check 应区分：

- `ERROR`
  - 结构非法
  - 数值违反硬约束
- `WARN`
  - 覆盖了全局 baseline
  - 偏离了仓库默认建议

### 10. 列表字段继续采用整体替换，而不是拼接

对于诸如 `gestures` 这类本轮采集清单字段：

- 继续用列表表达更自然
- 不需要列表拼接
- round profile 直接整体替换 global baseline 即可

因为这里的目标不是组合局部片段，而是声明“本轮要采哪些内容”。

### 11. live capture 态应考虑下沉到更底层的终端输入能力

当前实现用 `rich + questionary + stdin polling` 已经能跑通第一版，
但在以下场景存在风险：

- 倒计时提示与按键读取竞争
- `target_window` / `capture_window` 边界提示干扰结束键输入
- 单键结束打点对 capture 态 UI 控制能力提出更高要求

因此后续 live capture 态应考虑引入更底层的终端输入轮子，
使 capture 态与普通表单选择态分离。

当前倾向是：

- `Typer` 继续负责命令树
- `Rich` 继续负责摘要与静态渲染
- `Questionary` 继续负责普通表单与选择框
- live capture 态单独使用更底层的终端输入机制

## Alternatives Considered

### 1. 继续在 profile 中按 `gesture + speed` 写死 `target_window.start_s / end_s`

没有采用。

原因：

- `target_window` 将不再是固定落在 5 秒内某一段的静态窗口
- `speed` 也不再适合作为 collection 输入字段
- 与新的“隐藏 `capture_window` + 固定 `GO`”运行时模型冲突

### 2. 继续要求 operator 显式打 `marked_window` 的开始点

没有采用。

原因：

- operator 负担更高
- 与固定 `GO` 的语义不一致
- 更难收敛成稳定的单键结束工作流

### 3. 把全局配置继续做成多层目录递归叠加

当前没有采用。

原因：

- 当前真实需求更接近“root global + round profile”
- 继续做目录递归层叠会过早引入 merge 复杂度
- 当前目标是仓库复用，而不是目录级采集计划复用

### 4. 拒绝所有 profile 对 global 的覆盖

没有采用。

原因：

- 仓库复用需要保留临时调整能力
- 后续将通过 config check 的 `WARN` 来管理 override
- 强行禁止覆盖会降低工程实用性

### 5. 保留 `speed`，继续作为显式输入字段

当前没有采用。

原因：

- 预计消费价值不高
- 后续更可靠的做法是从 `marked_window` 或派生时长反推
- 保留它只会继续耦合 `target_window` 设计

## Consequences

该计划会直接带来以下影响：

- 2026-04-10 契约中的一部分字段语义将被后续实现重构
- `target_window` 从“静态预配置窗口”转为“运行时生成窗口”
- `marked_window` 从“双端人工打点”转为“自动开始 + 人工结束”
- `speed` 将从 collection 输入与 manifest 主字段中退场
- 全局 `rd.toml` 的角色会变成仓库级 baseline，而不是单轮业务 profile
- reject 裁决将逐步从 collection 状态机迁到 `quick QC`
- accepted 样本与 rejected attempt 的边界会更清楚
- live capture 态需要更强的终端输入能力支持

## Next Actions

1. 定义 `configs/collection/rd/global.toml` 的 schema
2. 定义 round profile 相对于全局 baseline 的 merge 规则
3. 删除 `speed` 并改写 `gesture -> target_window_duration_s` 配置结构
4. 重新定义 take attempt 的运行时窗口生成逻辑
5. 为 collection 增加最小可用的 `quick QC` 原型
6. 重新设计 live capture 态的按键输入与倒计时提示
7. 补一份与新运行时语义匹配的协作者操作文档

## Verification / Open Questions

已确认：

- `GO` 固定在 5 秒倒计时结束时
- `capture_window` 对 operator 隐藏
- `target_window` 只配置 duration，不再配置起止
- `marked_window` 自动开始，operator 只打结束点
- reject 统一收口到 `quick QC`
- rejected attempt 不进入正式样本集
- `speed` 可从 collection 输入契约中移除
- 全局配置只承载稳定、底层、声明性的字段
- profile 允许覆盖 global，并由检查脚本发 `WARN`

尚未真正实现：

- `configs/collection/rd/global.toml`
- 运行时随机 `capture_window` 放置逻辑
- 最小 `quick QC` 原型
- live capture 态与终端输入能力重构
- 结束键从 `m` 切换到 `space`
