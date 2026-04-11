# 仓库统一配置目录与分层策略

## Meta

- Date: 2026-04-11
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
  - `README.md`
  - `configs/`
  - `rd.toml`
  - `configs/profile_3d.cfg`
  - `configs/rd_phase1_uart.cfg`
  - `configs/collection/rd/rd_phase1_default.toml`
  - `configs/collection/rd/rd_template.toml`
  - `docs/dev/context/20260410_repo_structure_survey.md`
  - `docs/dev/context/20260411_capture_runtime_window_and_global_config_plan.md`
  - `docs/dev/context/20260411_capture_cfg_registry_policy.md`
  - `src/vassago/collection/rd/config.py`
  - `src/vassago/firmware/mmwave/config.py`

## Background

`20260410_repo_structure_survey.md` 已经明确指出：

- 根目录应把 `configs/` 作为一等公民边界
- `cfg` 应单独治理
- 仓库处于适合做结构重构的阶段

随后，`20260411_capture_runtime_window_and_global_config_plan.md` 把
collection 配置先收敛成了：

- 一个仓库级 global baseline
- 一个 round profile

但第一版落地时，global baseline 暂时放成了仓库根的 `rd.toml`。

这在 capture 讨论里是可行的过渡方案，但从 repo 结构角度看，它会带来两个问题：

- config 没有被统一收口到 `configs/`
- 随着训练、部署、一次性实验和治理资源继续增加，根目录会重新变脏

用户随后进一步明确提出：

- 无论是 collection、training、deployment 还是其他阶段
- 无论是全局 baseline、长期可复用配置还是一次性配置
- 都希望统一在一处管理

因此需要新增一份 repo 级 context，覆盖“整个仓库 config 应该怎样收口到 `configs/`”。

本文件是 repo 级目录策略，优先级高于先前 capture 文档里关于“根目录 `rd.toml`”
的临时放置假设。

## Decision / Findings

### 1. `configs/` 成为仓库内唯一的 repo-managed config home

当前正式决定：

- 所有 repo-managed 配置文件都应位于 `configs/` 下
- 根目录不再直接承载某个业务域的配置文件
- 根目录只保留项目级入口与顶层基础设施文件

这意味着：

- `rd.toml` 这种业务域 global baseline 不应继续放在仓库根
- 未来 training / edge / collection / firmware 的配置也不应再绕开 `configs/`
- 之前计划放在根目录的 `config_registry/` 也应并入 `configs/`

### 2. 目录组织采用“按域优先，再按角色细分”，而不是“按文件类型平铺”

当前推荐组织原则：

- 第一层先按业务域分
- 第二层再按角色分

原因：

- 以后不仅有 `.cfg` 和 `.toml`
- 还有 collection、training、edge、firmware 等不同消费方
- 同一种文件格式在不同域里的语义完全不同

因此不采用：

- `configs/globals/*.toml`
- `configs/profiles/*.toml`
- `configs/*.cfg`

这类“按文件角色或后缀先分”的平铺结构。

### 3. 当前最佳实践目录树应调整为下面这版

推荐目录树：

```text
configs/
  registry/
    catalog_roots.toml
    mmwave_cfg_commands.toml

  firmware/
    mmwave/
      baseline_pointcloud.cfg
      rd_candidate.cfg

  collection/
    rd/
      global.toml
      profiles/
        rd_phase1_default.toml
      templates/
        rd_template.toml

  training/
    global.toml
    experiments/
    templates/

  edge/
    global.toml
    deployments/
    templates/

  local/
    ...
```

这棵树里各目录的职责固定为：

- `configs/registry/`
  - 存放 catalog roots、命令表、schema policy 这类治理资源
- `configs/firmware/mmwave/`
  - 存放可被 operator / collection / smoke-test 复用的 mmWave cfg
- `configs/collection/rd/global.toml`
  - 存放 RD collection 的仓库级 baseline
- `configs/collection/rd/profiles/`
  - 存放可被实际选择和执行的 round profile
- `configs/collection/rd/templates/`
  - 存放脚手架模板，不直接进入 active selection
- `configs/training/`
  - 存放训练主域配置
- `configs/edge/`
  - 存放部署/落地主域配置
- `configs/local/`
  - 存放本机或个人临时 override
  - 默认应视为可 `gitignore`

### 4. 当前仓库的即时迁移目标应是“先把现有 config 收进正确域”，而不是一步做完所有未来域

当前最小、但方向正确的迁移目标是：

- `rd.toml`
  - 从仓库根迁到 `configs/collection/rd/global.toml`
- `configs/profile_3d.cfg`
  - 迁到 `configs/firmware/mmwave/`
- `configs/rd_phase1_uart.cfg`
  - 迁到 `configs/firmware/mmwave/`
- `configs/collection/rd/rd_phase1_default.toml`
  - 迁到 `configs/collection/rd/profiles/`
- `configs/collection/rd/rd_template.toml`
  - 迁到 `configs/collection/rd/templates/`
- 原先计划中的 `config_registry/`
  - 直接改为 `configs/registry/`

这样做的好处是：

- 只动当前真实已经存在的域
- 不会为了未来 training / edge 预先造很多空目录
- 但未来再扩展 training / edge 时，位置和规则已经清楚

### 5. `config_id` 仍是主键，目录重整不会改变这一点

本文件不改变前一份 capture policy 的核心结论：

- `config_id` 是主键
- 路径和文件名只是 locator
- 重命名和迁移目录不应打断关联

正因为如此，现在做目录重整是安全且值得的：

- 代码和配置的关联不应依赖 `rd.toml` 这个文件名
- 也不应依赖 `configs/profile_3d.cfg` 这种旧路径

如果实现足够干净：

- 路径变化只会影响 discovery roots 和 snapshot source path
- 不会影响 config 之间的主键引用关系

### 6. `configs/registry/` 是 config home 的一部分，不应再单独放在根目录

上一份 capture policy 里提出过：

- 在根目录新增 `config_registry/`

现在正式修正为：

- 所有治理型配置资源统一放在 `configs/registry/`

原因：

- 这些文件本质上也是配置
- 用户已经明确要求把“全局的、一次性的、治理用的”配置都收口到一处
- 把治理资源放在根目录会重新制造第二个 config home

### 7. `global.toml` 目前建议按“域内固定文件”落位，而不是急着抽成 `globals/`

从纯抽象角度看，未来也可以用：

- `configs/collection/rd/globals/default.toml`
- `configs/training/globals/default.toml`

但结合当前仓库状态，先不建议一步走到这层。

当前更平衡的方案是：

- `configs/collection/rd/global.toml`
- `configs/training/global.toml`
- `configs/edge/global.toml`

原因：

- 当前每个域真实只需要一个 baseline
- 另一边代码已经接近完成，不适合再为了“可能有多个 global”过度抽象
- 以后若真的出现多个 baseline，再升级到 `globals/` 目录也不晚

### 8. 一次性配置也要在 `configs/` 下，但要区分“版本化一次性”与“本机临时”

“一次性配置”实际上至少有两类：

- 版本化的一次性实验配置
- 本机临时 override

推荐处理方式：

- 可复盘、需要进入版本历史的
  - 放在对应域下的 `profiles/`、`experiments/`、`deployments/`
- 只服务于个人机器、端口、路径或临时调试的
  - 放在 `configs/local/`
  - 默认不纳入 repo-managed catalog

因此“都在一处管理”的含义是：

- 都在 `configs/` 这棵树下
- 但不是都混在同一个目录里

### 9. 当前 discovery roots 应同步收敛到新的目录树

一旦目录树调整，discovery 根也应同步明确为：

- `mmwave_cfg`
  - `configs/firmware/mmwave/**/*.cfg`
- `collection_rd_global`
  - `configs/collection/rd/global.toml`
- `collection_rd_profile`
  - `configs/collection/rd/profiles/*.toml`
- templates
  - `configs/**/templates/*`
  - 不默认进入 active selection
- registry resources
  - `configs/registry/*.toml`

### 10. training / edge 当前可以先只保留目录约束，不急着定义 schema

当前可以明确的是位置，不必现在就写死 schema。

也就是说：

- 先决定 training config 应该在 `configs/training/`
- 先决定 edge config 应该在 `configs/edge/`
- 但不必在本轮同时决定它们的字段结构和命令行消费方式

这样既能把 repo 结构先定住，也不会把这轮 capture 主题拉得过宽。

## Alternatives Considered

### 1. 继续把 `rd.toml` 放在仓库根

没有采用。

原因：

- 与“`configs/` 是一等公民 config home”的仓库结构方向冲突
- 后续 training / edge 跟进时会不断向根目录泄漏域配置
- 容易把临时过渡路径误固化成长期结构

### 2. 只把 `rd.toml` 挪进 `configs/`，其他配置继续平铺

没有采用。

原因：

- 只能解决一个文件的位置问题
- 不能解决 firmware / collection / training / edge 之间的边界问题
- 很快又会出现新的平铺膨胀

### 3. 现在就设计一个非常深的多层配置系统

当前没有采用。

原因：

- 另一边代码已经接近完成
- 这轮更重要的是先把 config home 收口到 `configs/`
- 先做域边界和角色边界，比先做复杂继承层次更重要

## Consequences

该策略落地后，会产生以下直接影响：

- capture 相关文档里“根目录 `rd.toml`”的说法将被视为过渡期表述
- `src/vassago/collection/rd/config.py` 中的默认 global path 后续应迁到 `configs/collection/rd/global.toml`
- firmware cfg 的默认发现根将从当前 `configs/` 平铺路径迁到 `configs/firmware/mmwave/`
- 后续 training / edge 配置可以直接接入同一棵 `configs/` 树，而不需要重新讨论“放哪里”

## Next Actions

1. 以本文件为 repo 级依据，修正 capture 相关 context 中对 `rd.toml` 和 `config_registry/` 的路径假设。
2. 让另一边代码在最终合并前，把 global path 从仓库根迁到 `configs/collection/rd/global.toml`。
3. 在实现 catalog 时，把治理资源目录固定为 `configs/registry/`。
4. 在真正移动 firmware cfg 前，再统一更新 smoke-test 文档、tests 和 snapshot 路径预期。
5. training / edge 在未来接入时，直接遵守本文件的域优先目录规则。

## Verification / Open Questions

已确认：

- 用户希望所有 repo-managed config 都统一收口到 `configs/`
- 根目录 `rd.toml` 不符合这个目标
- 这轮最需要先定的是 config home 和目录边界，而不是更复杂的继承系统

仍需在真正实施前确认的点：

- firmware cfg 文件名是否也顺便对齐 `config_id`
- `configs/local/` 是否默认加入 `.gitignore`
