# Context 目录说明

`docs/dev/context/` 用于保存用户明确要求保留的关键调查、分析结论和决策留痕。

它不是 AI 的自动思考日志，也不是所有改动都必须更新的目录。

## 触发规则

AI 默认不创建也不更新 context 文件。

如果 AI 判断某次变更或调查可能会显著影响后续开发判断，AI 应先提醒用户这次内容可能值得留痕。

只有在用户明确要求保留时，才创建或更新 `docs/dev/context/`。

## 适合保留到这里的内容

- 用户要求长期保留的结构调查与结论
- 用户要求长期保留的架构决策
- 用户要求长期保留的数据契约分析
- 用户要求长期保留的工作流取舍说明

## 不适合保留到这里的内容

- AI 默认产生的过程性思考
- 稳定 SOP
- 环境安装教程
- 普通命令清单
- 没有被用户要求保留的例行改动背景

## 文件命名规则

统一采用：

```text
YYYYMMDD_<scope>_<topic>.md
```

规则说明：

- `YYYYMMDD`: 形成该版本上下文的日期
- `scope`: 变更主域，例如 `repo`、`capture`、`signal`、`training`、`workflow`
- `topic`: 简短、稳定、可搜索的 snake_case 主题

示例：

- `20260410_repo_structure_plan.md`
- `20260411_capture_cfg_registry_policy.md`
- `20260412_training_dataset_contract.md`

## 文件格式

每份 context 文档都应尽量采用统一结构：

1. `Meta`
2. `Background`
3. `Decision` 或 `Findings`
4. `Alternatives Considered`
5. `Consequences`
6. `Next Actions`
7. `Related Files / Related Commits`

可直接参考模板：

- [_template.md](/Users/skd/Documents/vscode-projects/vassago/docs/dev/context/_template.md)

## 与 commit log 的关系

如果用户要求某次调查或决策被长期保留，相关 context 应尽量贴着对应 commit 走。

推荐做法：

- 一份 context 对应一个清晰主题
- context 尽量与其相关变更保持相近的提交时间
- commit 信息中应能看出此次改动对应的主题
- 如果存在 commit body，尽量显式记录对应的 context 文件路径
- tutorials 规范和具体 context 通常不要混在同一次提交里
- context 文档内部应记录相关文件、验证方式和后续动作

如果当下还没有真正创建 commit，可以先在 `Related Commits` 中写 `pending`，待提交完成后补齐。
