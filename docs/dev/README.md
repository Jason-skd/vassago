# 开发者文档入口

`docs/dev/` 面向开发者和 AI coding agent。

这里回答的问题是：

- 修改这个仓库前应该先读什么
- 开发工作流和提交边界应该怎么执行
- 哪些内容属于稳定规范
- 哪些内容属于用户要求保留的项目上下文

## Before Editing

如果你准备修改仓库结构、开发工作流、核心模块或关键文档，请先按顺序阅读：

1. [tutorials/README.md](/Users/skd/Documents/vscode-projects/vassago/docs/dev/tutorials/README.md)
2. [tutorials/development-workflow.md](/Users/skd/Documents/vscode-projects/vassago/docs/dev/tutorials/development-workflow.md)
3. [context/README.md](/Users/skd/Documents/vscode-projects/vassago/docs/dev/context/README.md)
4. `docs/dev/context/` 下与你当前任务直接相关、且由用户明确要求保留的 context 文件

## Directory Guide

- [tutorials/README.md](/Users/skd/Documents/vscode-projects/vassago/docs/dev/tutorials/README.md)
  稳定、可重复执行的开发规范与教程。
- [context/README.md](/Users/skd/Documents/vscode-projects/vassago/docs/dev/context/README.md)
  用户确认保留的关键调查、分析和决策留痕。

## Rules

- 稳定规范不要写进具体 context 文件
- 项目上下文不要默认自动生成
- AI 认为某次变更可能值得保留时，应先提醒用户
- 只有用户要求留痕后，才创建或更新 `docs/dev/context/`
