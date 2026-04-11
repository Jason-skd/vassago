# Config ID 注册、目录嗅探与校验工作流策略

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
  - `docs/dev/context/20260411_capture_runtime_window_and_global_config_plan.md`
  - `docs/dev/context/20260411_repo_config_tree_policy.md`
  - `configs/collection/rd/global.toml`
  - `configs/firmware/mmwave/*.cfg`
  - `configs/collection/rd/templates/rd_template.toml`
  - `configs/collection/rd/profiles/*.toml`
  - `.lefthook.yaml`
  - `docs/dev/tutorials/development-workflow.md`
  - `docs/dev/tutorials/environment-setup.md`
  - `src/vassago/firmware/mmwave/config.py`
  - `src/vassago/collection/rd/config.py`
  - `../vassago.bak/configs/rd_phase1_uart.cfg`
  - `../vassago.bak/configs/oob_pointcloud_ti_xwr68xx_aop.cfg`
  - `../vassago.bak/src/vassago/processing/mmwave/config.py`
  - `../mmWave-Radar-Research/configs/profile_3d.cfg`

## Background

`20260411_capture_runtime_window_and_global_config_plan.md` 已经把 `collection`
配置重构到“两层模型”。

`20260411_repo_config_tree_policy.md` 又进一步固定了 repo 级目录边界：

- 所有 repo-managed config 都应收口到 `configs/`
- capture 域的 global baseline 不应继续放在仓库根
- 治理型配置资源也应并入 `configs/registry/`

因此当前 capture 配置治理层的前提应修正为：

- `configs/collection/rd/global.toml` 负责仓库级 baseline
- round profile TOML 负责本轮采集意图
- `speed` 退出 collection 输入契约
- `target_window` 改为运行时生成，配置里只保留 duration

当前仓库已经出现这条迁移线的中间态：

- 代码当前仍临时引用仓库根的 `rd.toml`
- `configs/collection/rd/templates/rd_template.toml` 已经开始表达新 schema
- `src/vassago/collection/rd/config.py` 已开始加载 global + round profile
- 旧的 `cfg` 选择链路仍在 `src/vassago/firmware/mmwave/config.py` 中手写注册表
- `collection` 与 `firmware cfg` 之间仍保留 `config_path` 这种路径绑定
- `.lefthook.yaml` 目前只把 Python 文件纳入 pre-commit 自动检查

也就是说，运行时 schema 正在被另一边推进，但“配置治理层”还没有定下来：

- 目录嗅探还没有统一抽象
- `config_id` 还没有成为仓库级主键
- 元数据还没有迁移到统一的注释头
- `cfg` 命令表还没有 machine-readable 维护方式
- 配置校验还没有进入 hook 和开发工作流

本文件的职责不是推翻 `global baseline + round profile` 方案，而是明确它落地之后的下一层：

- 所有受管理 config 如何被发现
- 所有受管理 config 如何用 `config_id` 关联
- `cfg` 命令表放在哪里维护
- 校验脚本如何分层
- 校验脚本如何接入 `lefthook` 和开发工作流

## Decision / Findings

### 1. 本策略承接 `global baseline + round profile`，不回退到旧的单层 TOML 方案

当前固定前提如下：

- `configs/collection/rd/global.toml` 作为仓库级 RD global baseline
- round profile 放在 `configs/collection/rd/profiles/*.toml`
- round profile 的正文语义继续围绕新 runtime 方案演化
- 本策略只处理 identity、discovery、validation、workflow integration

因此本文件不会重新引入：

- `gesture + speed -> target_window.start_s/end_s`
- 只有路径没有 `config_id` 的配置绑定
- 手写“已知 cfg 列表”

### 2. 受管理 config 分成三类，并分别按“目录根”嗅探，而不是按“文件名列表”硬编码

本仓库当前需要治理的 config kind 固定为：

- `mmwave_cfg`
  - 发现根：`configs/firmware/mmwave/**/*.cfg`
- `collection_rd_profile`
  - 发现根：`configs/collection/rd/profiles/*.toml`
- `collection_rd_global`
  - 当前推荐文件名：`global.toml`
  - 当前推荐位置：`configs/collection/rd/`
  - 但 discovery 最终不应依赖这个文件名本身

这里要区分两件事：

- 可以固定“发现根”
- 不能固定“有哪些可用文件”

也就是说：

- `configs/firmware/mmwave/`、`configs/collection/rd/` 这种目录根是契约的一部分
- `profile_3d.cfg`、`rd_phase1_uart.cfg`、`rd_phase1_default.toml` 这些文件名不是主键

### 3. `config_id` 成为仓库级主键，路径和文件名只保留为 locator

当前正式决定：

- 所有受管理 config 都必须有稳定 `config_id`
- `config_id` 在整个受管理 config 集合中全局唯一
- 所有代码与配置之间的关联，都以 `config_id` 为主
- `path` 只作为运行时 catalog locator 存在
- 任何 repo-managed config 的持久化快照中都不记录冗余 `path`

这条规则带来的直接要求是：

- 文件重命名不能导致代码或其他配置失联
- 文件移动目录时，只要 discovery 还能扫描到它，引用关系就不应断裂
- manifest / snapshot 不再依赖 `source_path`
- 配置关联和恢复都必须只依赖 `config_id`

对于 CLI 来说：

- `--config-id` 应成为 repo-managed config 的标准入口
- `--config /path/to/file` 只保留给仓库外部或临时文件
- 当 `--config` 指向的是仓库内受管理文件时，后续实现应反查其 `config_id`

### 4. 所有受管理 config 的机器可读元数据，统一迁到文件开头的注释元数据头

当前决定引入一段结构化 comment header，作为 discovery 层唯一读取的元数据来源。

建议格式不是自由文本注释，而是“注释包裹的 TOML header block”。示例：

`cfg` 文件示例：

```text
% --- vassago:meta ---
% config_kind = "mmwave_cfg"
% config_id = "baseline_pointcloud"
% label = "Baseline Point Cloud"
% description = "Conservative bring-up baseline."
% lifecycle = "active"
% risk = "low"
% recommended_for_bringup = true
% ---
```

round profile / global TOML 示例：

```text
# --- vassago:meta ---
# config_kind = "collection_rd_profile"
# config_id = "rd_phase1_default"
# label = "RD Phase 1 Default"
# description = "Default RD round profile."
# lifecycle = "active"
# ---
```

解析规则固定为：

- 只读取文件最前面的结构化 header block
- 读取时先去掉注释前缀
  - `cfg` 用 `%`
  - TOML 用 `#`
- 再按普通 TOML 片段解析
- header block 之外的自由说明性注释，不参与机器解析

统一 header 的原因是：

- 目录嗅探层不需要知道具体文件内容 schema
- `cfg` 与 TOML 可以复用一套 metadata loader
- `rd_template.toml` 这类模板文件可以通过 `lifecycle = "template"` 被 catalog 识别但默认不进入“可选配置列表”

### 5. collection TOML 正文的 schema 由另一边继续收敛，但 discovery metadata 先与正文解耦

当前正式决定：

- discovery 层只读取 comment header
- `config_id` / `label` / `description` / `lifecycle` 只允许出现在 header 中
- collection TOML 正文只保留 `schema_version` 与真正参与 runtime 的字段
- 正文中若继续出现重复 metadata，应直接报 `ERROR`

也就是说：

- `schema_version` 继续属于正文
- `config_id` 作为主键，只由统一 metadata header 承担 discovery 职责

### 6. `collection` 对 `firmware cfg` 的绑定只允许使用 `config_id`

在新的配置治理模型里，跨 config 引用必须满足：

- round profile 必须通过 `firmware.config_id` 绑定 mmWave cfg
- `firmware.config_path` 属于被禁止字段
- 任何 repo-managed config 内都不再允许保存冗余 path

对应地，manifest snapshot 应保留：

- `firmware.config_id`
- 本次 round profile 的 `config_id`
- 本次 global config 的 `config_id`

后续恢复关联时，只允许走 `config_id`。

### 7. 在 `configs/registry/` 下保存“需要人工维护、且应 machine-readable 的配置治理资源”

运行时配置仍然放在：

- `configs/collection/rd/global.toml`
- `configs/firmware/mmwave/**/*.cfg`
- `configs/collection/rd/profiles/*.toml`

新增的 `configs/registry/` 不放运行时 profile，而是放治理层资源。

当前建议至少包含：

- `configs/registry/catalog_roots.toml`
  - 定义哪些目录根会被当成受管理 config root
  - 定义每种 root 默认对应的 `config_kind`
- `configs/registry/mmwave_cfg_commands.toml`
  - 维护 mmWave cfg 命令表
  - 维护命令状态、参数个数、重复次数、推荐顺序与严重级别

这里的原则是：

- 高波动、需要用户维护的规则尽量数据化
- 纯 Python 类型约束与复杂语义推导仍保留在 `src/`

这样既不会把所有规则都塞进代码，也不会为了“全配置化”而把复杂逻辑写成难维护的数据 DSL。

### 8. `cfg` 命令表第一版应从三个来源收敛，并显式记录“支持状态”

第一版命令表来源固定为：

- 当前仓库现有样本：`configs/profile_3d.cfg`
- 当前仓库现有样本：`configs/rd_phase1_uart.cfg`
- 参考仓库：`../vassago.bak/configs/rd_phase1_uart.cfg`
- 参考仓库：`../vassago.bak/configs/oob_pointcloud_ti_xwr68xx_aop.cfg`
- 参考仓库：`../mmWave-Radar-Research/configs/profile_3d.cfg`

从这些样本收敛出的首批命令集合如下。

当前仓库与参考仓库都出现过、可作为第一版 `supported` 候选的命令：

- `sensorStop`
- `flushCfg`
- `dfeDataOutputMode`
- `channelCfg`
- `adcCfg`
- `adcbufCfg`
- `lowPower`
- `profileCfg`
- `chirpCfg`
- `frameCfg`
- `guiMonitor`
- `cfarCfg`
- `multiObjBeamForming`
- `calibDcRangeSig`
- `clutterRemoval`
- `compRangeBiasAndRxChanPhase`
- `measureRangeBiasAndRxChanPhase`
- `aoaFovCfg`
- `cfarFovCfg`
- `extendedMaxVelocity`
- `CQRxSatMonitor`
- `CQSigImgMonitor`
- `analogMonitor`
- `lvdsStreamCfg`
- `calibData`
- `sensorStart`

只在参考配置中出现、应显式记录状态的命令：

- `bpmCfg`
  - 当前更适合作为 `known_but_blocked` 或 `deny_by_default`
  - 原因是当前仓库已有失败提示把它视为“不受当前 firmware 支持”的代表命令

命令表不应只保存“命令名”，还应至少保存：

- `status`
  - 例如 `supported` / `known_but_blocked` / `deprecated`
- `arg_counts`
  - 允许的参数个数
- `min_occurs`
- `max_occurs`
- `required`
- `ordering_hints`
  - 例如 `sensorStart` 必须是最后一个实义命令
- `notes`
  - 说明来自哪个参考仓库或为何被阻止

### 9. `cfg` 校验应建立在“先 strip inline comment，再 tokenize”的前提上

参考仓库中的 `cfg` 存在大量如下写法：

```text
sensorStop             % comment
chirpCfg 0 0 0 0 0 0 0 1  % comment
```

因此 `cfg` checker 必须先做：

1. 去除行尾 inline comment
2. 再判断空行
3. 再切分命令与参数

否则命令表中的参数个数统计会被说明性注释污染。

### 10. 配置校验固定为两步，但第二步按 kind 分派具体规则

配置校验的总模型继续采用“两步”：

1. metadata / catalog check
2. kind-specific semantic check

第一步 `metadata / catalog check` 固定检查：

- 结构化 comment header 是否存在
- `config_kind` 是否合法
- `config_id` 是否存在且全局唯一
- `label` / `description` 是否完整
- `lifecycle` 是否合法
- 文件是否位于对应 kind 的合法 discovery root 下
- 正文中是否错误出现了 header-only metadata

第二步 `kind-specific semantic check` 固定按 kind 分派：

- `mmwave_cfg`
- `collection_rd_global`
- `collection_rd_profile`

#### 10.1 `mmwave_cfg` 的正文语义校验

这里的“正文语义校验”指的是：

- 不只看有没有 metadata
- 还要看 `cfg` 里的真实指令集合、顺序和已知约束是否成立

第一版至少检查：

- 是否出现未知命令
- 是否出现 `known_but_blocked` 命令
- required 命令是否缺失
- singleton 命令是否重复
- `sensorStop` 是否出现在前部
- `sensorStart` 是否为最后一个实义命令
- `channelCfg` / `profileCfg` / `frameCfg` 是否存在
- `chirpCfg` 是否至少出现一次
- `cfarCfg` / `cfarFovCfg` 是否满足当前命令表里的最小出现次数

第一版还应复用旧仓库里已经被证明有价值的派生检查：

- `channelCfg` 的 RX / TX mask 都必须启用至少一个通道
- `profileCfg` 的 `numAdcSamples` 必须为正
- `frameCfg` 的 chirp 区间必须合法
- `frameCfg` 的 loop count 必须为正
- 每帧 chirp 数必须能被启用的 TX 天线数整除

#### 10.2 `collection_rd_global` 的正文语义校验

这里的“正文语义校验”指的是：

- `configs/collection/rd/global.toml` 的 runtime baseline 字段是否齐全
- 数值约束是否成立
- 其结构是否能被 round profile 合法覆盖

第一版至少检查：

- `schema_version` 是否匹配当前 global schema
- `capture_window_duration_s` 是否为正
- `countdown_duration_s` 是否为正
- `marked_window_end_grace_s` 是否 >= 0
- `end_mark_key` 是否属于允许集合
- `[serial]` 表中的波特率是否为正整数

#### 10.3 `collection_rd_profile` 的正文语义校验

这里的“正文语义校验”指的是：

- round profile 的业务字段是否齐全
- 它与 global baseline merge 后是否仍然合法
- 它引用的 `firmware cfg` 是否存在于 catalog

由于另一边仍在同步 round/global schema，本策略只固定最外层要求，不绑定到某一份临时草稿字段名。

但无论具体字段如何微调，第一版 checker 都必须覆盖：

- `schema_version` 是否匹配当前 round profile schema
- `batch_size` 是否为正
- `[firmware].config_id` 是否存在且可解析到 `mmwave_cfg`
- 是否错误出现 `[firmware].config_path`
- `options.gestures` 是否为非空、唯一字符串列表
- `options.environments` 是否为非空、唯一字符串列表
- `defaults` 中的必填字段是否完整
- 默认环境是否存在于 `options.environments`
- `gesture_target_durations` 是否与 `options.gestures` 一一对应
- 每个 target duration 是否为正
- target duration 与 grace / capture window 的几何关系是否成立
- profile 对 global baseline 的覆盖是否落在允许字段集合内

### 11. 校验结果固定分成 `ERROR` 与 `WARN`，以支持 global override 与迁移期兼容

当前正式决定：

- 结构非法、主键冲突、引用失效、冗余 path、重复 metadata，这些报 `ERROR`
- baseline override、模板文件误放、`bpmCfg` 这类已知但不推荐命令，这些报 `WARN`

典型 `ERROR`：

- 重复 `config_id`
- header 缺失
- `firmware.config_id` 无法解析
- `firmware.config_path` 仍然存在
- `sensorStart` 不在最后

典型 `WARN`：

- round profile 覆盖了 global baseline
- `bpmCfg` 出现在 cfg 中
- 文件被标成 `lifecycle = "template"` 却放在 active 目录里

### 12. 校验核心逻辑应放在 `src/`，dev-only 入口放在 `scripts/`

当前推荐分层如下：

- `src/vassago/config_registry/`
  - comment header parser
  - catalog builder
  - config id resolver
  - mmWave cfg validator
  - collection global/profile validator
- `scripts/`
  - `check_configs`
  - `scaffold_collection_rd_profile`

这样分层的原因是：

- 校验逻辑本身会被 CLI、hook、测试、脚手架复用
- 这些核心逻辑属于仓库能力，应放在 `src/`
- 交互式引导和一次性批处理属于 dev tooling，应先放在 `scripts/`
- 当前不应把这类 dev 工具混入 operator 命令树

因此“放 `src` 还是 `scripts`”的结论不是二选一，而是：

- 核心在 `src`
- 薄入口在 `scripts`

### 13. 本轮不保留 dev 交互式 TOML 写入工具

当前正式决定：

- 本轮聚焦 configs 目录树、格式规范、文件发现与文件检查
- 不保留面向 dev 的交互式 TOML 写入工具
- `templates/` 目录只提供人工编辑的骨架文件

### 14. 配置校验必须进入所有开发工作流，而不只是一个独立脚本

当前固定要求如下：

- `.lefthook.yaml`
  - 增加专门的 config check 命令
  - 触发范围至少覆盖：
    - `configs/collection/rd/global.toml`
    - `configs/**/*.cfg`
    - `configs/**/*.toml`
- `docs/dev/tutorials/development-workflow.md`
  - 在提交前检查项中加入 config check
- `docs/dev/tutorials/environment-setup.md`
  - 在常用命令与 hook 说明中加入 config check

注意：

- 在实现真正落地前，不应把这些未来命令提前写进稳定教程，避免文档先于实现漂移
- 但一旦校验脚本落地，上述工作流文档必须在同一轮主题内同步更新

## Alternatives Considered

### 1. 继续维护手写“已知 cfg 列表”

没有采用。

原因：

- 每新增一个 `cfg` 都要改代码
- 文件重命名会造成不必要的代码耦合
- 与用户要求的“嗅探目录 + 自动读元数据”相冲突

### 2. 继续让 `config_path` 承担主绑定关系

没有采用。

原因：

- 文件名和目录变化会打断关联
- 不符合“整个仓库以 `config_id` 为主键管理 config”的目标
- 不利于后续把 discovery、UI、snapshot 统一起来

### 3. 把校验规则全部硬编码在 Python 中，不引入新的根目录资源文件

没有采用。

原因：

- `cfg` 命令表本身就是高波动、适合人工维护的数据
- 用户已明确愿意维护一份命令表
- 适度数据化比把所有命令知识散落在代码里更稳

### 4. 继续保留基于 path 的兼容字段或迁移期

没有采用。

原因：

- 用户已明确要求不保留迁移期概念
- 冗余 path 会继续污染 snapshot 与配置契约
- 一次性切到纯 `config_id` 更干净

### 5. 把交互式引导脚本直接塞进现有 operator CLI

当前没有采用。

原因：

- 这类工具是 dev workflow，不是 operator workflow
- 它依赖模板、校验、catalog，更适合作为 `scripts/` 的薄入口
- 先放 `scripts/` 更容易控制边界

## Consequences

该策略落地后，会带来以下直接变化：

- `src/vassago/firmware/mmwave/config.py` 的手写注册表将被 catalog 替代
- `collection` 与 `firmware cfg` 的路径耦合会消失
- 受管理 config 的可选列表将由目录嗅探和 metadata header 自动生成
- `rd_template.toml` 这类模板文件可以被 catalog 识别但默认不进入 active selection
- `cfg` 命令可用性会从“散落知识”收口到一份显式命令表
- config check 会成为开发流程的一等公民，而不是提交前靠记忆手动跑

## Next Actions

1. 以后续实现显式引用本文件作为配置治理层基准。
2. 固定 comment header block 语法，并把 `lifecycle` 一并纳入。
3. 固定 `configs/registry/` 的最小文件集，先落 `catalog_roots.toml` 与 `mmwave_cfg_commands.toml`。
4. 让所有 repo-managed config 都补上 `config_id` 导向的 metadata header。
5. 实现 catalog builder，把 `config_id` 作为统一主键。
6. 实现两步 checker，并先接入 `scripts/`。
7. 再把 checker 接入 `.lefthook.yaml` 与开发者教程。
9. 最后补交互式 round profile scaffold。

## Verification / Open Questions

已确认：

- 本策略承接 `global baseline + round profile`，不回退到旧 schema
- 所有受管理 config 都应以 `config_id` 为主键
- 不保留任何 path 持久化或迁移期兼容层
- discovery 应嗅探目录根，而不是维护文件名白名单
- `cfg` 命令表应从当前仓库与两个参考仓库收敛
- 校验脚本必须进入 `lefthook` 与开发工作流
- 本轮不保留交互式 TOML 写入脚手架

仍需在实现前最后拍板的点：

- firmware cfg 文件名是否顺便对齐 `config_id`
