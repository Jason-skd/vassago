# 开发工作流与提交规范

本文档用于固定本项目的稳定开发工作流。

它不是一次性的项目调查记录，也不是某次架构讨论本身。它只保留长期有效的规则。

## 1. 提交边界

一次提交只处理一个清晰主题。

适合作为单独提交的例子：

- 一个目录重构
- 一次 CLI 拆分
- 一组同主题文档整理
- 一次测试分层调整

不适合作为同一次提交的例子：

- 顺手混入不相关修复
- 一边改教程，一边新增具体 context
- 一边改结构，一边再补无关命名清理

## 2. AI 的 checkpoint 责任

当 AI 认为当前工作已经形成自然提交边界时，应主动停下来汇报，而不是继续把下一个主题混进来。

这条规则同样适用于“小但已经完整、而且值得单独提交”的工作。

对于这类工作，AI 不应默认继续往下做下一个主题，而应先进入“等待用户验收 + 准备提交”的状态。

汇报至少应包含：

- 已完成什么工作
- 可以如何验证
- 还未验证或仍有风险的点
- 建议的 commit message

如果 AI 判断当前工作已经可以单独提交，汇报中应明确表达：

- 这是一项已经形成自然提交边界的小工作
- 当前适合先请用户验收
- 当前适合单独提交
- 建议的 commit message 是什么

如果当前改动对应已存在或即将新增的 context，也应一并指出。

## 3. Context 的默认规则

AI 默认不创建也不更新 `docs/dev/context/`。

如果 AI 认为某次调查、结构取舍或决策可能会影响后续开发判断，应先提醒用户这次内容可能值得保留为 context。

只有用户明确要求保留时，才创建或更新 context 文件。

## 4. tutorials 与 context 的提交关系

稳定规范文档和具体项目 context 通常不要放在同一次提交里。

推荐做法：

- 规范类更新单独提交
- 用户要求保留的具体 context 单独提交

只有当用户明确要求合并时，才考虑把两者放在同一提交里。

## 5. Conventional Commits

本项目统一使用 conventional commits：

```text
type(scope): summary
```

推荐 `type`：

- `feat`
- `fix`
- `refactor`
- `docs`
- `test`
- `chore`

`scope` 应贴近主域，例如：

- `repo`
- `docs`
- `capture`
- `signal`
- `training`
- `eval`
- `edge`
- `cli`

示例：

- `docs(dev): define development workflow and context trigger rules`
- `docs(readme): simplify repository entry and reading order`
- `refactor(cli): split firmware and capture entrypoints`

## 6. 带 context 的 commit

如果某次提交对应一个用户要求保留的 context，建议在 commit body 中显式写明：

```text
Context: docs/dev/context/<file>.md
```

## 7. 最低要求

在没有用户明确要求的情况下，不要自动新增 context。

在已经形成自然提交边界时，不要继续把第二个主题混入当前工作。

## 8. 分析实施计划和代码简洁度要求

AI 当被要求制定实施计划时, 需要主动分析是否有可以用上现成的轮子, 并提醒用户添加依赖, 时刻需要保持代码简洁易读, 而不是尝试自己 solve anything.

## 9. Configs 管理策略

本仓库已经有一套完整的 `configs/` 管理策略，不要把它当成“随便放几个 toml / cfg 的目录”。

在当前实现里，配置管理至少包含这几层：

- catalog discovery：哪些目录受管、哪些文件会被扫描，不由业务代码临时 `glob` 决定，而由 registry 和 catalog 固定
- metadata contract：每个受管 config 都必须带结构化 header，`config_id` 是主键，不是文件路径
- kind-specific semantic validation：不同 kind 的 config 有各自的正文约束，不是“能 parse 就算过”
- mmWave cfg integrity：受管 mmWave cfg 第一次进入 catalog 时会记录内容 hash，之后内容必须保持不变

因此，改 `configs/` 时先分清楚什么能改，什么不能改。

可以改的：

- 新增一个 config 文件，只要它放在受管目录、header 完整、`config_id` 唯一
- 修改 collection profile / global 这类 TOML 的正文，但必须仍满足该 kind 的字段契约
- 新增一份 mmWave cfg，用新的 `config_id` 表达一条新配置路线
- 在 profile 里改默认绑定关系，例如默认选中的 firmware cfg

不能随手改的：

- 不要直接改已有受管 mmWave cfg 的正文，把它当“原地继续调参数”的草稿
- 不要复用已有 `config_id`
- 不要在业务层写 `config_path` 或磁盘路径绕开 catalog
- 不要把 header-only metadata 混回 TOML body
- 不要把 active / template 文件长期放错目录角色

正确改法：

1. 先确定你改的是哪一类 config，以及它应该放在哪个受管目录。
2. 先写对 header，再改正文；不要反过来。
3. 如果是 collection profile / global，优先改正文里的业务字段，不要绕过 `config_id` 绑定。
4. 如果是 mmWave cfg，新增需求优先新建一份 cfg，而不是直接修改已有已受管 cfg。
5. 新 mmWave cfg 第一次进入 catalog 时，validation 会自动为“registry 中还没有记录”的 `config_id` 追加 hash。
6. 一旦某个 mmWave cfg 已经有 hash 记录，后续 validation 只允许它内容不变；如果内容漂移，会直接报错而不会刷新 hash。

当前 validation / hook 会检查这些事：

- 受管目录里的 metadata header 是否可解析，`config_kind` 是否和目录角色一致
- `config_id` 是否全局唯一
- lifecycle 和目录角色是否冲突
- header-only key 是否被误写进 TOML body
- mmWave cfg 是否只使用 registry 允许的命令，命令顺序、参数个数和派生约束是否成立
- collection global / profile 是否满足字段契约，引用的 `config_id` 是否能在 catalog 里解析
- mmWave cfg integrity registry 是否缺项、是否有未知项、以及已有 hash 是否与实际内容一致

处理 `configs/` 相关改动时，默认先跑：

- `uv run python -m vassago.configs.validation`

如果这一步失败，不要先猜业务逻辑，先把 config contract 修正到通过。

## 10. Python 改动的默认验收

只要改动涉及 Python 代码，默认验收至少应覆盖：

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pyright`
- 与改动直接相关的 `uv run pytest ...`

如果任务范围较大，或者无法明确缩小测试范围，则直接运行 `uv run pytest`。

## 11. 静态检查豁免规则

对 `ruff` 和 `pyright`，默认不要使用以下豁免手段：

- `# noqa`
- `# type: ignore`
- `# pyright: ignore`

只有在不用这些豁免会显著增加代码复杂度、并且明显得不偿失时，才允许例外。

如果 AI 在实现中新增、扩大或保留了这类豁免，必须在验收汇报和提交前显式说明：

- 使用了什么豁免
- 具体位于哪个文件
- 为什么不能直接通过更清晰的代码或类型建模解决

## 12. Codex 的 Git 提权规则

在 Codex 沙箱里，`git add` 和 `git commit` 通常会被拦截。

因此当任务明确要求：

- stage 文件
- 创建 commit
- 改写尚未 push 的本地 commit message

正确做法是：

- 直接为对应 git 命令申请提权
- 使用非交互 git 命令
- 在真正执行 `git commit` 前，先确认 commit message 已符合 conventional commit

不要做的事：

- 先假设 `git add` / `git commit` 能直接通过
- 因为沙箱限制去改用更绕的临时方案
- 在已经知道需要写 `.git/` 的情况下，先做一轮明知会失败的 plain-text 追问
