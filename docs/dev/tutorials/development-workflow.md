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

## 9. Python 改动的默认验收

只要改动涉及 Python 代码，默认验收至少应覆盖：

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pyright`
- 与改动直接相关的 `uv run pytest ...`

如果任务范围较大，或者无法明确缩小测试范围，则直接运行 `uv run pytest`。

## 10. 静态检查豁免规则

对 `ruff` 和 `pyright`，默认不要使用以下豁免手段：

- `# noqa`
- `# type: ignore`
- `# pyright: ignore`

只有在不用这些豁免会显著增加代码复杂度、并且明显得不偿失时，才允许例外。

如果 AI 在实现中新增、扩大或保留了这类豁免，必须在验收汇报和提交前显式说明：

- 使用了什么豁免
- 具体位于哪个文件
- 为什么不能直接通过更清晰的代码或类型建模解决
