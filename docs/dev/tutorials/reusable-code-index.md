# 项目可复用代码索引

这份文档是写给“准备在仓库里继续加功能的人”看的。

目标只有一个：新增代码前，先确认仓库里有没有已经可复用的实现，避免把相同逻辑再平行写一份，最后把仓库继续堆成难读难改的屎山。

如果你是 AI coding agent，这份文档应和 [development-workflow.md](development-workflow.md) 一起视为必读规范。

一句话原则：

- 先复用
- 再扩展
- 最后才是新开模块

## 1. 先建立一个正确心智模型

当前仓库已经不是“什么都没有”的状态。

至少下面这些基础能力已经存在，而且已经被 CLI、采集流程和测试复用：

- repo-managed config 发现、元数据解析和全量校验
- mmWave cfg 解析、串口探测、cfg 上传和 UART 包解析
- RD collection profile 加载、session manifest 管理、采集执行和 quick QC

所以大多数新增需求，不应该从 `Path.glob()`、`serial.Serial(...)`、`json.dumps(...)`、手写 prompt、手写 packet parser 重新开始。

## 2. 使用这份索引时，先问自己 4 个问题

开始写代码前，先问：

1. 我现在要处理的是路径、配置、串口、UART 数据、session，还是 CLI 接线？
2. 这个需求是不是已经在另一个工作流里做过一遍？
3. 我是应该扩展库层函数，还是只是在 CLI 层接线？
4. 我是不是正准备复制一段和现有模块八成相似的逻辑？

如果第 4 个问题答案是“是”，先停一下，回到下面索引找现成代码。

## 3. Config Tree 与路径基础设施

这一组模块负责“配置文件在哪里、怎么发现、怎么按 `config_id` 找到、怎么做全量校验”。

### [src/vassago/configs/paths.py](../../../src/vassago/configs/paths.py)

优先复用场景：

- 需要把 repo-relative path 转成绝对路径
- 需要把绝对路径回写成 repo-relative path
- 需要稳定拿到仓库根目录

优先复用的函数：

- `repo_root()`
- `resolve_repo_path()`
- `to_repo_relative_path()`

不要再做的事：

- 在多个模块里手写 `Path(__file__).parents[...]`
- 自己拼 `configs/...` 或 `data/...` 的绝对路径
- 在 manifest 或输出里混用绝对路径和相对路径

### [src/vassago/configs/models.py](../../../src/vassago/configs/models.py)

优先复用场景：

- 需要统一表达 `ConfigKind`、`ConfigLifecycle`
- 需要传递 catalog entry 或 validation issue

优先复用的类型：

- `ConfigKind`
- `ConfigLifecycle`
- `ConfigMetadata`
- `CatalogEntry`
- `ValidationIssue`

### [src/vassago/configs/metadata.py](../../../src/vassago/configs/metadata.py)

优先复用场景：

- 需要读取 `.toml` 或 `.cfg` 文件头部的结构化 metadata
- 需要检查 header-only key 的边界

优先复用的函数与常量：

- `parse_metadata_header()`
- `HEADER_ONLY_KEYS`

不要再做的事：

- 直接把文件头当普通注释跳过
- 在多个地方各写一套 `config_id` / `label` / `lifecycle` 解析逻辑

### [src/vassago/configs/catalog.py](../../../src/vassago/configs/catalog.py)

优先复用场景：

- 需要发现仓库里全部受管理配置
- 需要按 `config_id` 找到某个 config 文件
- 需要拿到某个 kind 的 active 配置

优先复用的函数：

- `load_catalog()`
- `load_root_specs()`
- `discover_paths()`
- `ConfigCatalog.require_entry()`
- `ConfigCatalog.require_single_active()`

最重要的原则：

- 需要“发现配置”时，优先走 catalog，不要自己在业务代码里到处 `glob`

### [src/vassago/configs/validation.py](../../../src/vassago/configs/validation.py)

优先复用场景：

- 需要对整个 `configs/` 树做统一验证
- 需要在命令行或 CI 中跑全量配置检查

优先复用的函数与入口：

- `validate_all_configs()`
- `run_config_discovery()`
- `run_config_validation()`
- `run_config_validation_context()`
- `uv run vassago configs validate`

它已经帮你串起：

- catalog discovery
- duplicate `config_id` 检查
- peer-style config checks 编排
- 新增 mmWave cfg 时的 first-seen integrity 记录追加

最重要的原则：

- 需要“跑一整轮 configs 校验”时，优先扩展或复用这里的 orchestrator
- 不要把 discovery、peer checks 和 CLI 渲染重新混写在一起

### [src/vassago/configs/checks.py](../../../src/vassago/configs/checks.py)

优先复用场景：

- 需要给 `vassago configs validate` 增加一个新的 peer check
- 需要单独调用 entry-location、semantics 或 mmWave integrity 检查
- 需要把某个 kind-specific 校验接到统一 report 里

优先复用的函数与常量：

- `run_entry_location_check()`
- `run_config_semantics_check()`
- `run_mmwave_cfg_integrity_check()`
- `DEFAULT_CONFIG_VALIDATION_CHECKS`

它已经处理：

- lifecycle 与目录角色一致性检查
- header-only metadata key 泄漏到 TOML body 的错误
- mmWave cfg 语义校验的 report 包装
- RD collection global / profile loader 级校验
- mmWave cfg integrity 检查接线

不要再做的事：

- 在 `validation.py`、`cli.py` 或测试里临时塞一段匿名校验逻辑当长期方案
- 为了新增一个 configs 检查，就绕开统一 `ValidationContext` / `ValidationReport`

### [src/vassago/configs/validation_contract.py](../../../src/vassago/configs/validation_contract.py)

优先复用场景：

- 需要定义新的 config validation plugin
- 需要共享 configs 校验的 message / report / context 模型
- 需要把多个 checks 的结果合并成一次稳定输出

优先复用的类型与常量：

- `ValidationMessage`
- `ValidationReport`
- `ValidationContext`
- `ValidationRunResult`
- `ConfigValidationCheck`
- `merge_reports()`
- `CONFIG_VALIDATION_PLUGIN_DISCOVERY`
- `CONFIG_VALIDATION_PLUGIN_ENTRY_LOCATION`
- `CONFIG_VALIDATION_PLUGIN_SEMANTICS`
- `CONFIG_VALIDATION_PLUGIN_MMWAVE_INTEGRITY`

最重要的原则：

- 不要在新的 configs 检查器里再发明一套 message schema
- plugin id、report 聚合和 error/warn 口径优先沿用这里

### [src/vassago/configs/mmwave_cfg_integrity.py](../../../src/vassago/configs/mmwave_cfg_integrity.py)

优先复用场景：

- 需要读取或校验 mmWave cfg integrity registry
- 需要为新加入的受管 cfg 追加 digest 记录
- 需要计算 path-independent 的 cfg 内容 hash

优先复用的函数与类型：

- `load_mmwave_cfg_integrity_registry()`
- `clear_mmwave_cfg_integrity_cache()`
- `compute_mmwave_cfg_digest()`
- `build_mmwave_cfg_integrity_records()`
- `format_mmwave_cfg_integrity_registry()`
- `append_missing_mmwave_cfg_integrity_records()`
- `validate_mmwave_cfg_integrity()`
- `MmwaveCfgIntegrityRecord`

它已经处理：

- cfg 文本规范化后的稳定 digest 计算
- registry 结构校验
- 缺项 / 未知 `config_id` / hash mismatch 检查
- 只追加新 cfg 记录、不覆盖旧 hash

不要再做的事：

- 手写 `sha256` 比较逻辑
- 为了“让检查过掉”直接覆盖既有 cfg 的 digest 基线
- 在脚本里绕开 registry，临时认可受管 cfg 内容漂移

### [src/vassago/configs/ui.py](../../../src/vassago/configs/ui.py)

优先复用场景：

- 需要渲染 configs catalog 表格
- 需要以统一格式输出 config validation summary

优先复用的函数：

- `render_catalog_entries()`
- `render_validation_report()`

最重要的原则：

- configs CLI handler 只做接线；表格和 summary 样式尽量复用这里
- 不要在多个命令里各写一份 `result/errors/warnings` 文本输出

## 4. mmWave 固件、串口与 UART 复用面

这一组模块负责“cfg 怎么解析、串口怎么发现、怎么上传 cfg、怎么读数据、怎么解析 packet”。

### [src/vassago/firmware/mmwave/cfg.py](../../../src/vassago/firmware/mmwave/cfg.py)

优先复用场景：

- 需要读取 `.cfg` 命令行
- 需要去掉注释、拿到行号、命令名和参数

优先复用的函数与类型：

- `strip_inline_comment()`
- `load_cfg_lines()`
- `load_cfg_commands()`
- `CfgCommand`

不要再做的事：

- 自己用 `splitlines()` 临时处理 cfg 注释
- 在上传 cfg、校验 cfg、统计 cfg 时各写一套解析

### [src/vassago/firmware/mmwave/config_validation.py](../../../src/vassago/firmware/mmwave/config_validation.py)

优先复用场景：

- 需要验证某一份 mmWave cfg 是否符合仓库约束
- 需要读取命令 registry

优先复用的函数：

- `validate_cfg()`
- `load_command_registry()`

它已经覆盖：

- 命令是否在 registry 中注册
- 参数个数是否正确
- `sensorStart` 是否位于最后
- 必需命令和出现次数约束
- `channelCfg` / `profileCfg` / `frameCfg` 的派生约束

### [src/vassago/firmware/mmwave/config.py](../../../src/vassago/firmware/mmwave/config.py)

优先复用场景：

- 需要拿到“仓库内置、对人可读的 mmWave cfg 列表”
- 需要把 `config_id` 解析成具体 `.cfg` 文件

优先复用的函数与类型：

- `list_known_configs()`
- `get_known_config()`
- `KnownMmwaveConfig`

最重要的原则：

- 业务层如果是“消费仓库管理下的 mmWave cfg”，优先传 `config_id`，不要四处硬编码磁盘路径

### [src/vassago/firmware/mmwave/ports.py](../../../src/vassago/firmware/mmwave/ports.py)

优先复用场景：

- 需要列出现有串口
- 需要筛出更像 mmWave 候选的串口

优先复用的函数与类型：

- `list_serial_ports()`
- `list_candidate_mmwave_ports()`
- `SerialPortInfo`

不要再做的事：

- 在多个 CLI 里重复写串口候选规则
- 到处散落 `cp210` / `Silicon Labs` 判断

### [src/vassago/firmware/mmwave/protocol.py](../../../src/vassago/firmware/mmwave/protocol.py)

优先复用场景：

- 需要解析 TI-style mmWave UART packet
- 需要把 packet 汇总成 smoke-test 或采集摘要

优先复用的函数与类型：

- `MmwavePacketParser`
- `MmwavePacket`
- `MmwaveTlv`
- `SmokeTestSummaryAccumulator`
- `SmokeTestSummary`
- `summarize_packets()`

它已经处理：

- magic word 对齐
- buffer 中的噪声恢复
- packet header 解析
- TLV payload 最佳努力解析
- streaming summary 累加
- frame gap、非单调 frame 统计

最重要的原则：

- 需要 packet/TLV 边界时，先扩展或复用这里
- 不要在 GUI、collection 或一次性脚本里再各写一套 magic word 对齐和 TLV 遍历

### [src/vassago/firmware/mmwave/point_cloud.py](../../../src/vassago/firmware/mmwave/point_cloud.py)

优先复用场景：

- 需要从 mmWave packet 或原始字节流里提取点云
- 需要在 live capture 和离线 replay 中共用同一套点云解码逻辑
- 需要构造后续切割、点云缓存或可视化要消费的语义帧

优先复用的函数与类型：

- `PointCloudStreamDecoder`
- `PointCloudFrame`
- `PointCloudPoint`
- `extract_point_cloud_frame()`
- `iter_point_cloud_frames()`
- `decode_point_cloud_tlv()`

它已经处理：

- 基于共享 packet parser 的点云流式解码
- 点云 TLV payload 到 `(x, y, z, velocity)` 语义点的转换
- live / replay 共用的点云 frame 模型

不要再做的事：

- 在 visualizer、cutting、exporter 里各自手写一份点云 TLV 解析
- 让 GUI 模块继续承担长期协议解析职责

### [src/vassago/firmware/mmwave/smoke_test.py](../../../src/vassago/firmware/mmwave/smoke_test.py)

优先复用场景：

- 需要给 CLI 口发送 cfg
- 需要验证 cfg 下发是否成功
- 需要读 Data UART 并产出 smoke-test 摘要
- 需要 probe 多个端口并推断 CLI/Data 角色

优先复用的函数与类型：

- `send_config()`
- `validate_cli_session()`
- `run_smoke_test()`
- `collect_probe_results()`
- `infer_port_roles()`
- `build_recovery_hint()`
- `CliSessionResult`
- `PortProbeResult`

这就是当前仓库里 `smoke-test` 的库层实现。

不要再做的事：

- 在 `collection`、新 CLI 或一次性脚本里再写一份 cfg 上传逻辑
- 再写一份 probe 端口和角色推断逻辑
- 自己重新维护一套“命令失败怎么看”的恢复提示

### [src/vassago/firmware/mmwave/ui.py](../../../src/vassago/firmware/mmwave/ui.py)

优先复用场景：

- 新增 mmWave 相关 CLI 交互或表格输出

优先复用的函数：

- `render_serial_ports()`
- `render_probe_results()`
- `render_known_configs()`
- `render_smoke_test_summary()`
- `prompt_for_known_config()`
- `prompt_for_port()`

最重要的原则：

- CLI handler 只做接线，展示和交互尽量走 `ui.py`

## 5. RD Collection 复用面

这一组模块负责“profile 怎么加载、session 怎么落盘、live capture 怎么执行、quick QC 怎么做”。

### [src/vassago/collection/rd/config.py](../../../src/vassago/collection/rd/config.py)

优先复用场景：

- 需要列出 collection profiles
- 需要按 `config_id` 找一个 profile
- 需要加载 `global.toml`
- 需要拿到 profile 的 effective runtime snapshot

优先复用的函数与类型：

- `list_collection_profiles()`
- `get_collection_profile()`
- `load_collection_profile()`
- `load_collection_global_config()`
- `CollectionProfile`
- `CollectionGlobalConfig`
- `WindowRange`

它已经处理：

- metadata header 校验
- profile 和 global 合并
- `defaults.firmware_config_id` 绑定校验
- serial defaults 合并
- `gesture_target_durations` 约束
- `config_snapshot` 生成

不要再做的事：

- 手写 `tomllib.load()` 后自己到处拼字段
- 在其他模块里重复实现 profile/global 合并逻辑

### [src/vassago/collection/rd/paths.py](../../../src/vassago/collection/rd/paths.py)

优先复用场景：

- collection 模块内需要 repo 路径辅助函数

这一层本质上是 `configs.paths` 的别名出口，避免 collection 模块自己再发明一套路径工具。

### [src/vassago/collection/rd/session.py](../../../src/vassago/collection/rd/session.py)

优先复用场景：

- 初始化 session manifest
- 列出未完成 session
- 更新 session 状态
- 接受 take 并写回 manifest
- 生成 raw capture 输出路径
- 维护 manifest 顶层 public contract 和 `config_snapshot` 的落盘结构

优先复用的函数与类型：

- `SessionInitInput`
- `initialize_session()`
- `build_session_manifest()`
- `list_unfinished_sessions()`
- `count_accepted_takes()`
- `count_remaining_takes()`
- `next_pending_take()`
- `accept_take()`
- `build_take_output_path()`

不要再做的事：

- 手动拼 `data/collection/rd/sessions/.../manifest.json`
- 在多个地方各写一份 manifest schema
- 自己更新 take 状态和路径字段
- 在别的模块里重新定义 top-level manifest contract

### [src/vassago/collection/rd/capture.py](../../../src/vassago/collection/rd/capture.py)

优先复用场景：

- 需要执行 live capture
- 需要把 raw UART 数据汇总成和 smoke-test 一致的摘要
- 需要把 live packet 结果分发给 summary、QC、visualizer 一类 consumer
- 需要在 collection 流程里重新配置雷达

优先复用的函数与类型：

- `run_session()`
- `capture_take()`
- `review_capture_take()`
- `summarize_raw_capture()`
- `read_available_bytes()`
- `RunSessionSummary`
- `AttemptPlan`

最重要的复用点：

- `capture.py` 明确复用了 `smoke_test.send_config()`、`smoke_test.validate_cli_session()` 和 `protocol` 解析能力
- live capture 已经提供“raw bytes -> shared packet parser -> 多个 consumer”的接线位置
- 如果你要扩展采集流程，优先沿着这条复用链走，不要把 `smoke-test` 逻辑再复制一遍

### [src/vassago/collection/rd/visualizer.py](../../../src/vassago/collection/rd/visualizer.py)

优先复用场景：

- 需要在 live capture 里接入点云可视化
- 需要把 parsed packet 转成 GUI 可消费的 `PointCloudFrame`
- 需要一个可关闭、不会阻塞主采集循环的可视化 consumer

优先复用的函数与类型：

- `start_visualizer()`
- `PointCloudVisualizerSession`
- `PointCloudVisualizerSession.consume_packets()`
- `PointCloudVisualizerSession.close()`

最重要的原则：

- visualizer 消费的是解析后的 packet/frame 结果，不是直接重写一套 UART/TLV parser
- GUI 失败或队列拥塞时，不能反向拖垮核心采集路径

### [src/vassago/collection/rd/quick_qc.py](../../../src/vassago/collection/rd/quick_qc.py)

优先复用场景：

- 需要基于当前 phase 规则做最小 quick QC
- 需要把 reason code 渲染为可读文本
- 需要复用 live / offline 共用的样本质量检查实现

优先复用的函数与类型：

- `run_quick_qc()`
- `evaluate_capture()`
- `describe_reason()`
- `QuickQcDecision`

它已经同时提供：

- peer-style `QcReport` 结果，用于后续 `offline_qc`
- live collection 当前仍在用的 `QuickQcDecision` 兼容层

### [src/vassago/collection/rd/metadata_qc.py](../../../src/vassago/collection/rd/metadata_qc.py)

优先复用场景：

- 需要校验 manifest top-level public contract
- 需要校验 take-level contract 是否完整
- 需要校验 top-level 和 `config_snapshot` 的 mirror / membership / default 对照关系

优先复用的函数与常量：

- `run_metadata_qc()`
- `CODE_MISSING_FIELD`
- `CODE_INVALID_FIELD`
- `CODE_TAKE_COUNT_MISMATCH`
- `CODE_SNAPSHOT_MISMATCH`
- `CODE_MEMBERSHIP_VIOLATION`

最重要的原则：

- 不要在别处再平行写一套 manifest contract validator
- top-level 与 snapshot 的合规关系优先沿用这里的实现和 `qc_contract` 常量

### [src/vassago/collection/rd/offline_qc.py](../../../src/vassago/collection/rd/offline_qc.py)

优先复用场景：

- 需要对一个 session manifest 跑完整离线 QC
- 需要把多个 peer checks 聚合为一个 `QcReport`
- 需要对 accepted takes 重放 live `quick_qc`

优先复用的函数与常量：

- `run_offline_qc()`
- `run_offline_qc_context()`
- `run_offline_quick_qc()`
- `CODE_MISSING_REPLAY_INPUT`
- `CODE_RAW_UART_NOT_FOUND`

最重要的原则：

- `offline_qc` 是 orchestrator，不是随手堆规则的地方
- 新的离线 QC 检查优先按 peer check 接入，而不是把逻辑全塞进 CLI

### [src/vassago/collection/rd/qc_contract.py](../../../src/vassago/collection/rd/qc_contract.py)

优先复用场景：

- 需要定义新的 collection QC plugin
- 需要共享 live / offline QC 的 finding/report 模型
- 需要复用 manifest 顶层 contract 和 snapshot 对照规则

优先复用的类型与常量：

- `QcFinding`
- `QcReport`
- `merge_reports()`
- `QuickQcContext`
- `MANIFEST_TOP_LEVEL_EXTRACT_FIELDS`
- `MANIFEST_TOP_LEVEL_SELECTION_FIELDS`
- `MANIFEST_TOP_LEVEL_OPTION_FIELDS`
- `MANIFEST_TAKE_EXTRACT_FIELDS`
- `MANIFEST_SNAPSHOT_COMPARISON_RULES`
- `MANIFEST_SNAPSHOT_MEMBERSHIP_RULES`

最重要的原则：

- 不要在 `quick_qc`、`offline_qc`、extractor 或新 CLI 里各自再发明一套 finding schema
- 不要把 manifest 顶层字段清单和 snapshot 对照规则复制到多个模块里

### [src/vassago/collection/rd/ui.py](../../../src/vassago/collection/rd/ui.py)

优先复用场景：

- 新增 collection 相关 CLI 交互
- 需要统一 session、take、quick QC 的输出样式

优先复用的函数：

- `render_collection_profiles()`
- `render_sessions()`
- `render_session_summary()`
- `render_take_state()`
- `render_capture_summary()`
- `render_quick_qc()`
- `prompt_for_collection_profile()`
- `prompt_for_session()`
- `prompt_take_action()`
- `prompt_take_decision()`

### [src/vassago/collection/rd/cli.py](../../../src/vassago/collection/rd/cli.py)

这不是“逻辑堆放区”，而是当前 collection CLI 的接线层。

优先复用场景：

- 需要新增 collection 子命令时，沿用当前 handler 组织方式
- 需要参考“库层先行、CLI 薄层接线”的写法

读这个文件时，重点不是复制 handler 里的每一段，而是看它怎么把下面这些库层模块串起来：

- `config.py`
- `session.py`
- `capture.py`
- `ui.py`
- `firmware/mmwave/*`

## 6. 命令入口本身也值得复用

### [src/vassago/cli.py](../../../src/vassago/cli.py)

如果你要新增 CLI，不要另起一套入口。

优先做法：

- 在现有 Typer 树下挂子命令
- 沿用 `register_commands()` 这种组织方式
- 让新命令复用现有库层模块，而不是把业务逻辑写进 handler

## 7. 测试文件也是复用示例

如果你不确定某个模块该怎么用，先看测试。

推荐优先参考：

- [tests/test_configs.py](../../../tests/test_configs.py)
  看 catalog、peer check、自定义 validation report 和 integrity registry 怎么调用。
- [tests/test_mmwave_smoke_test.py](../../../tests/test_mmwave_smoke_test.py)
  看 cfg 上传、端口角色推断和恢复提示怎么测。
- [tests/test_mmwave_protocol.py](../../../tests/test_mmwave_protocol.py)
  看 packet parser 和摘要怎么使用。
- [tests/test_collection_config.py](../../../tests/test_collection_config.py)
  看 profile 加载和 snapshot 怎么用。
- [tests/test_collection_session.py](../../../tests/test_collection_session.py)
  看 session manifest 的初始化和查询怎么用。
- [tests/test_collection_quick_qc.py](../../../tests/test_collection_quick_qc.py)
  看 quick QC 的共享检查和 live 兼容层怎么用。
- [tests/test_collection_offline_qc.py](../../../tests/test_collection_offline_qc.py)
  看 metadata QC、offline quick-QC replay 和 `offline-qc` CLI 怎么用。
- [tests/test_collection_cli.py](../../../tests/test_collection_cli.py)
  看 CLI 如何薄层接线到库层模块。
- [tests/test_collection_visualizer.py](../../../tests/test_collection_visualizer.py)
  看 visualizer packet consumer 怎样复用共享 parser 和点云 frame 解码。

## 8. 常见任务应该先复用什么

如果你现在要做的是：

- “按 `config_id` 找配置”
  先看 `configs.catalog`、`firmware.mmwave.config`、`collection.rd.config`
- “给 `configs validate` 增加或拆分 peer check”
  先看 `configs.validation`、`configs.checks`、`configs.validation_contract`
- “校验或更新 mmWave cfg integrity registry”
  先看 `configs.mmwave_cfg_integrity`
- “渲染 configs catalog / summary”
  先看 `configs.ui`
- “读取或校验 mmWave cfg”
  先看 `firmware.mmwave.cfg`、`firmware.mmwave.config_validation`
- “给板子重新下发 cfg”
  先看 `firmware.mmwave.smoke_test.send_config()`
- “判断 cfg 上传是否真的成功”
  先看 `firmware.mmwave.smoke_test.validate_cli_session()`
- “解析 UART 原始数据”
  先看 `firmware.mmwave.protocol` 和 `collection.rd.capture.summarize_raw_capture()`
- “管理采集 manifest / take 状态”
  先看 `collection.rd.session`
- “做最小 quick QC”
  先看 `collection.rd.quick_qc`
- “跑完整离线 QC”
  先看 `collection.rd.offline_qc`
- “校验 manifest contract / snapshot 对照关系”
  先看 `collection.rd.metadata_qc`
- “定义 collection QC finding / report / manifest contract”
  先看 `collection.rd.qc_contract`
- “给 CLI 加交互”
  先看 `firmware.mmwave.ui` 或 `collection.rd.ui`

## 9. 什么时候才应该新开模块

只有在下面几种情况下，才值得新开一份实现：

- 现有模块的职责边界确实不覆盖你的问题
- 硬塞进现有模块会让抽象明显更混乱
- 用户明确要求做结构拆分

除此之外，默认策略都应该是：

- 先在现有模块上扩展
- 让新调用方复用旧逻辑
- 让 CLI 继续保持薄层接线

如果你准备新增代码，而这份文档里已经能找到 70% 以上相似职责的模块，优先复用，不要平行再写一套。
