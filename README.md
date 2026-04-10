# Vassago

Vassago 是一个面向高精度、高鲁棒性微动手势边缘 AI 识别的毫米波雷达仓库。

项目长期关注以下链路：

- 固件与硬件 bring-up
- 原始数据采集与质检
- 雷达信号表示与数据契约
- 深度学习训练、评估与实验管理
- 边缘部署与模型导出

## Current Repository Status

当前仓库仍处于重构前的骨架阶段。

当前真实存在的顶层结构只有：

- `src/vassago/`
  当前最小可导入库包。
- `docs/`
  项目文档系统。
- `scripts/`
  辅助脚本目录。
- `pyproject.toml`
  项目元数据与依赖入口。
- `.python-version`
  当前固定 Python 版本。

## Required Reading Before Editing

如果你是 AI coding agent 或开发者，并且准备修改以下内容：

- 仓库结构
- 开发工作流
- 核心模块
- 重要文档

请先按顺序阅读：

1. [docs/dev/README.md](/Users/skd/Documents/vscode-projects/vassago/docs/dev/README.md)
2. [docs/dev/tutorials/development-workflow.md](/Users/skd/Documents/vscode-projects/vassago/docs/dev/tutorials/development-workflow.md)
3. [docs/dev/context/README.md](/Users/skd/Documents/vscode-projects/vassago/docs/dev/context/README.md)
4. `docs/dev/context/` 下与你当前任务直接相关、且由用户明确要求保留的 context 文件

如果你是协作者而不是仓库维护者，请先阅读：

1. [docs/collaborators/README.md](/Users/skd/Documents/vscode-projects/vassago/docs/collaborators/README.md)

## Important Documents

- [docs/README.md](/Users/skd/Documents/vscode-projects/vassago/docs/README.md)
  文档系统总入口。
- [docs/dev/README.md](/Users/skd/Documents/vscode-projects/vassago/docs/dev/README.md)
  开发者阅读入口。
- [docs/collaborators/README.md](/Users/skd/Documents/vscode-projects/vassago/docs/collaborators/README.md)
  协作者阅读入口。
