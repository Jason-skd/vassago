# 今晚实施计划与 CLI 依赖决策

## Meta

- Date: 2026-04-10
- Scope: repo
- Status: active
- Requested By: Jason-skd
- Authors:
  - Jason-skd
  - Codex
- Related Branch: `main`
- Related Commits:
  - pending
- Related Files:
  - `pyproject.toml`
  - `README.md`
  - `docs/dev/context/20260410_repo_structure_survey.md`
  - `../vassago.bak/src/vassago/firmware/mmwave/cli.py`
  - `../vassago.bak/src/vassago/collection/rd/cli.py`
  - `../vassago.bak/src/vassago/collection/rd/capture.py`
  - `../vassago.bak/src/vassago/collection/rd/quality.py`
  - `../vassago.bak/configs/rd_phase1_uart.cfg`
  - `../mmWave-Radar-Research/configs/profile_3d.cfg`
  - `../mmWave-Radar-Research/src/data_collector.py`
  - `../mmWave-Radar-Research/src/parser.py`

## Background

当前 `vassago` 主仓库仍处于骨架阶段，尚未落地 `smoke_test`、`collection`、`QC` 三条主流程代码。

用户要求先不做实现与文档收口，而是先完成两件事：

- 调查今晚主线开发前需要准备好的依赖与实施顺序
- 把与 `.bak` 仓库不同的新流程约束提前固定下来

在本轮调查中，同时对两个参考仓库进行了职责拆分：

- `vassago.bak`：提供工程化主流程、CLI、会话模型、采集切流经验和 QC 逻辑
- `mmWave-Radar-Research`：提供更保守、更稳定的点云 `cfg` 路径，以及点云采集研究原型

用户随后又明确提出一个额外约束：

- `numpy` 属于数据处理阶段依赖，不应在当前阶段加入主仓库运行依赖

## Decision / Findings

### 1. 今晚主线仍以 `.bak` 为工程母本

今晚的 `smoke_test`、`collection`、`QC` 三件事，不应从 `mmWave-Radar-Research` 直接迁移。

原因：

- 该仓库本质上是点云采集研究原型
- 它没有 `probe-ports`、session manifest、operator batch workflow、quick QC、offline QC 这类工程流程
- 它适合作为 `cfg` 经验来源，不适合作为主线 CLI 架构来源

因此主线应继承 `.bak` 的以下能力边界：

- 固件联调：`list-ports` / `probe-ports` / `smoke-test`
- 会话初始化与批量采集
- 结构化 `quality`
- 采集前后围绕 manifest 的状态与元信息管理

### 2. `cfg` 策略不应继续把 RD-over-UART 候选配置当默认基线

`mmWave-Radar-Research` 的 `profile_3d.cfg` 之所以显得更稳定，核心原因不是脚本写得更强，而是其输出路径更保守：

- 只输出 point cloud
- 串口带宽压力更低
- 固件兼容风险更低
- 配合 ROI、速度阈值和静态杂波过滤，研究闭环更短

相对地，`.bak` 中的 `rd_phase1_uart.cfg` 明确属于 RD-over-UART 候选配置：

- 输出体量更大
- 对固件状态更敏感
- 对串口链路和切流质量要求更高

因此今晚主线的 `cfg` 结论是：

- `profile_3d.cfg` 这一类保守点云配置，是稳定性参考源
- RD 主线仍需要独立治理稳定 `cfg`
- 不应把 `.bak` 的 `rd_phase1_uart.cfg` 继续视为“当然默认配置”

### 3. 点云 + RD 双采集是独立支线，不进入今晚三件事主线

用户提出的“点云 + RD 双采集、可视化和窗口标记”是合理方向，但当前应视为实验支线。

原因：

- `.bak` 现有处理链主要围绕 RD TLV 和 `raw_uart.bin -> rd.npz`
- 点云路径的数据契约、可视化链和标记语义尚未进入当前主仓库设计
- 若将其直接混入今晚主线，会显著抬高 `smoke_test`、`collection`、`QC` 三件事的耦合度

因此当前定位为：

- 主线：先跑通 RD 的三件事
- 支线：再探索点云 + RD 双采集与可视化

### 4. 新版 collection 必须从一开始支持三窗口语义

今晚如果开始落 collection，不应继续沿用 `.bak` 的 `fixed_window_v1` 语义作为最终模型。

新版 collection 需要从设计层直接纳入三类窗口：

- 大窗口：固定总采集时长 5s，覆盖所有动作前后背景
- 有效窗口：由 `collection_configs` 配置，按动作与速度定义“理想执行区间”
- 自定义窗口：由 operator 在动作开始瞬间和结束瞬间手动打点，记录真实窗口

这意味着：

- 旧版 manifest 字段只能作为参考，不能原样照搬为最终契约
- `QC` 后续不只做 packet 结构判断，还要消费窗口元信息
- `collection_configs` 在新架构里必须成为一等对象，而不是散在 prompt 默认值里

### 5. CLI 交互的目标是“简洁命令树 + 明确操作状态 + 勾选式输入”

新版 CLI 的目标不是“把 `.bak` 的 `argparse + input()` 原样搬过来”，而是降低样板代码并改善协作者体验。

当前确定的交互方向：

- 选择 `cfg` 不再输入路径，而是交互式勾选
- 选择串口不再手输设备名，而是从探测结果中选择
- 恢复 session 不再依赖手输 manifest 路径，而是从未完成会话列表中选择
- `collection` 流程要显式展示状态机，而不是只有回车和 `a/r/q`

### 6. 当前阶段推荐的 CLI 依赖边界

当前运行依赖已加入：

- `pyserial`

当前阶段不应加入：

- `numpy`
  原因：属于数据处理阶段依赖，不属于联调与交互阶段最低运行依赖

为实现“CLI 代码简洁”和“交互体验好”，推荐依赖组合如下：

- 必选：`typer`
  用于替换大段 `argparse` 样板代码，压缩命令树注册与 help 声明
- 必选：`questionary`
  用于提供 `select`、`checkbox`、路径选择、autocomplete 等交互能力
- 可选但推荐：`rich`
  用于表格、面板、状态摘要、进度显示和更清楚的 QC 输出

当前不建议加入：

- `textual`
  其定位已经偏向完整 TUI 应用，会把当前 CLI 复杂度整体抬高
- `prompt_toolkit`
  作为更底层库，当前阶段没有必要直接面向它开发
- 显式添加 `click`
  如果使用 `typer`，不需要再额外把 `click` 当成一层独立开发抽象来设计

### 7. `smoke_test` 需要先形成一个独立、稳定的最小闭环

今晚三件事的真正起点不是 collection，而是固件联调闭环。

`smoke_test` 当前应被明确理解为一个独立交付对象，其范围固定为：

- 列出当前主机可见串口
- 探测候选串口并推断 `CLI` / `Data` 角色
- 让 operator 交互式选择 `cfg`
- 让 operator 交互式确认 `cli_port` / `data_port`
- 对选定 `cfg` 执行最小 smoke test
- 在失败时给出清楚的恢复提示

当前不把以下内容并入 `smoke_test` 范围：

- session manifest
- collection 三窗口
- `quality`
- `raw_uart.bin` 落盘
- 点云可视化

### 8. `smoke_test` 的实现应按“库层先行、CLI 薄层接线”的方式推进

为避免回到 `.bak` 那种大 CLI 文件，`smoke_test` 应优先拆为以下职责：

- 协议层
  - magic word、packet parser、summary 聚合
- 串口能力层
  - 串口枚举
  - 候选端口探测
  - cfg 下发
  - CLI prompt 检测
- 交互层
  - 选择 cfg
  - 选择端口
  - 参数确认
- 命令层
  - 把参数模式与交互模式统一接到同一套库函数

这意味着：

- CLI 文件不应包含过多串口细节
- 底层探测与 summary 必须可单元测试
- 交互层必须可替换，以便保留非交互模式

### 9. `smoke_test` 的细化实施顺序已经固定

建议按下面顺序推进：

1. 先定文件边界与命令名
   - 明确 `list-ports`、`probe-ports`、`smoke-test` 三个入口
   - 先把目录职责切干净，再写实现
2. 再迁协议与 summary
   - 先让 packet parser、TLV 统计和 smoke summary 可用
3. 再迁 cfg 下发与 CLI prompt 检测
   - 包括命令发送、响应收集、startup prompt 判断
4. 再完成 `list-ports / probe-ports`
   - 让 operator 先拿到端口可见性和推荐角色
5. 再补 `cfg` 注册表
   - 不允许继续让 operator 手输路径作为主要交互方式
6. 再接 `smoke-test` 主流程
   - 选择 cfg
   - 确认端口
   - 跑 summary
   - 输出恢复提示
7. 再补测试
   - 协议层
   - 串口会话层
   - CLI 路由层
8. 最后做真机验证
   - 先跑 baseline point-cloud cfg
   - 再跑 RD cfg

### 10. `smoke_test` 内部可并行的任务已经明确

可以同时进行的任务：

- 协议解析层
  - packet parser
  - TLV 统计
  - smoke summary model
- 端口与交互层
  - 串口枚举
  - probe 结果整理
  - cfg 注册表
  - 交互式选择器
- 测试骨架
  - `test_mmwave_protocol`
  - `test_mmwave_smoke_test`
  - `test_cli`

不适合并行的任务：

- `smoke-test` 最终 handler 接线
  - 它依赖协议层、probe 层、cfg 选择层都先稳定
- 真机验证
  - 它依赖主流程已经连通
- 错误恢复文案收口
  - 最好等主要失败路径都实际跑通过后再统一整理

### 11. `smoke_test` 的第一轮验收标准应尽量窄而明确

第一轮只要求满足以下标准：

- `list-ports` 能稳定列出当前可见串口
- `probe-ports` 能输出候选端口和推荐角色
- operator 不需要手输 `cfg` 路径
- operator 不需要手输串口设备名
- baseline point-cloud cfg 能作为标准基线 smoke test 路径
- RD cfg 失败时，终端能给出明确恢复提示
- 命令同时支持：
  - 交互模式
  - 全参数非交互模式

### 12. `smoke_test` 当前建议的代码组织方向

如果开始落代码，建议优先朝下面这组文件边界组织：

- `src/vassago/cli.py`
- `src/vassago/__main__.py`
- `src/vassago/firmware/mmwave/protocol.py`
- `src/vassago/firmware/mmwave/ports.py`
- `src/vassago/firmware/mmwave/config.py`
- `src/vassago/firmware/mmwave/smoke_test.py`
- `src/vassago/firmware/mmwave/ui.py`
- `tests/test_mmwave_protocol.py`
- `tests/test_mmwave_smoke_test.py`
- `tests/test_cli.py`

这组边界的核心目的不是凑目录，而是避免：

- 把 probe 逻辑塞回 CLI 文件
- 把交互逻辑和串口逻辑耦在一起
- 把后续 collection 也继续堆进同一个入口模块

## Alternatives Considered

### 1. 直接沿用 `.bak` 的 `argparse + input()` 方案

没有采用。

原因：

- CLI 注册样板代码较多
- 交互过程仍偏“逐项问答”和手输路径
- 不利于把 `cfg`、串口、session、动作配置提升为交互式选择对象

### 2. 直接进入 `textual` 全屏 TUI

没有采用。

原因：

- 会显著提高架构复杂度
- 会把当前“命令式 CLI”改造成“事件式应用”
- 对今晚三件事主线不是最短路径

### 3. 把点云 + RD 双采集直接并入今晚主线

没有采用。

原因：

- 会让主线范围失控
- 会推迟 `smoke_test`、`collection`、`QC` 的最小闭环
- 现有 RD 契约与点云契约尚未统一

## Consequences

本次规划会直接带来以下影响：

- 新仓库的第一批运行依赖应围绕 `pyserial + typer + questionary (+ rich)` 组织
- `numpy` 保持在数据处理阶段再引入，不提前进入当前主线路径
- collection 的数据契约会从一开始就比 `.bak` 更复杂，但能避免后续二次返工
- 点云实验将被清晰隔离为支线，减少主线架构污染
- `cfg` 将被视为单独治理对象，而不是单纯的一份文本配置

## Next Actions

今晚实施顺序固定为：

1. 先落 `smoke_test`
   - 迁入 `.bak` 的 `list-ports` / `probe-ports` / `smoke-test`
   - 同时改造成交互式选择串口与 `cfg`
   - 先完成固件联调的独立闭环，再进入 collection
2. 再落 `collection`
   - 先定义三窗口模型和 `collection_configs`
   - 再设计 operator 交互状态机
3. 然后落 `QC`
   - 复用 `.bak` 的结构化 packet/QC 逻辑
   - 再补窗口元信息检查口径
4. 最后单开支线验证点云 + RD 双采集
   - 第一版只验证采集与可视化可行性
   - 不把它并入今晚主线闭环

## Verification / Open Questions

已确认：

- 当前主仓库仍是骨架阶段，主线代码需要重新落地
- `.bak` 适合作为工程流程母本
- `mmWave-Radar-Research` 适合作为保守 `cfg` 与点云原型参考
- `mmWave-Radar-Research` 并没有已沉淀好的可复用可视化实现，notebook 当前是空文件
- 当前仓库运行依赖中已经加入 `pyserial`
- `numpy` 当前不应加入主线运行依赖

尚未确认：

- `typer`、`questionary`、`rich` 是否会全部作为 runtime dependency 落入主仓库，还是其中一部分放入可选 group
- `collection_configs` 最终采用 TOML、JSON 还是 Python schema 驱动
- 自定义窗口第一版是否只采用键盘打点，还是后续升级为更强交互界面
- `smoke_test` 第一版是否直接引入 `rich`，还是先用 `typer + questionary` 落最小交互闭环
