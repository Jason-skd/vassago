# Vassago

Vassago 是一个面向高精度、高鲁棒性微动手势边缘 AI 识别的毫米波雷达仓库。

项目长期关注以下链路：

- 固件与硬件 bring-up
- 原始数据采集与质检
- 雷达信号表示与数据契约
- 深度学习训练、评估与实验管理
- 边缘部署与模型导出

## Current Repository Status

当前仓库已经落地以下最小可用闭环：

- repo-managed `configs/` 目录树
- mmWave `list-ports / probe-ports / smoke-test`
- RD `collection` profile 加载、session manifest 与可恢复采集流程
- 面向开发者与协作者的双层文档系统

仍然在持续迭代，但已经不是“只有骨架”的状态。

## Repository Structure

当前仓库主要目录建议按下面这张图理解：

```text
.
├── configs/
│   ├── collection/rd/
│   │   ├── global.toml
│   │   ├── profiles/
│   │   └── templates/
│   ├── firmware/mmwave/
│   └── registry/
├── data/
│   └── collection/rd/sessions/
├── docs/
│   ├── collaborators/
│   └── dev/
├── scripts/
├── src/vassago/
│   ├── collection/rd/
│   ├── configs/
│   └── firmware/mmwave/
├── tests/
├── pyproject.toml
├── uv.lock
└── .python-version
```

各目录职责：

- `configs/`
  仓库正式管理的配置树。包含 mmWave `.cfg`、RD collection TOML，以及配置发现/校验所需的 registry。
- `data/`
  运行期采集产物目录。当前主要用于 `collection` session manifest 和 `raw_uart.bin`。
- `docs/`
  项目文档系统。开发规范在 `docs/dev/`，协作者操作文档在 `docs/collaborators/`。
- `scripts/`
  辅助脚本目录。当前内容较少，保留给后续稳定脚本。
- `src/vassago/`
  主 Python 包。
  `configs/` 负责配置发现、元数据解析与校验。
  `firmware/mmwave/` 负责串口探测、cfg 上传、包解析与 bring-up CLI。
  `collection/rd/` 负责 profile、manifest、采集执行与 quick QC。
- `tests/`
  当前最小回归测试集，覆盖 configs、mmWave、collection 三条主线。
- `pyproject.toml` / `uv.lock`
  项目依赖、CLI 入口与锁定版本。
- `.python-version`
  当前固定 Python 版本。

## Required Reading Before Editing

如果你是 Codex 或其他 AI coding agent，那么每次新建对话、并准备在这个仓库里开展工作时，都应自主先阅读：

1. [docs/dev/tutorials/development-workflow.md](docs/dev/tutorials/development-workflow.md)
2. [docs/dev/tutorials/reusable-code-index.md](docs/dev/tutorials/reusable-code-index.md)

不要等用户额外提醒。

这两份文档是必须一起执行的 AI 规范：

- `development-workflow.md`
  约束提交边界、checkpoint 和工作流。
- `reusable-code-index.md`
  约束优先复用仓库现有模块，避免平行复制逻辑、避免把代码继续堆成难读难改的屎山。

如果你是 AI coding agent 或开发者，并且准备修改以下内容：

- 仓库结构
- 开发工作流
- 核心模块
- 重要文档

请先按顺序阅读：

1. [docs/dev/README.md](docs/dev/README.md)
2. [docs/dev/tutorials/development-workflow.md](docs/dev/tutorials/development-workflow.md)
3. [docs/dev/tutorials/reusable-code-index.md](docs/dev/tutorials/reusable-code-index.md)
4. [docs/dev/context/README.md](docs/dev/context/README.md)
5. `docs/dev/context/` 下与你当前任务直接相关、且由用户明确要求保留的 context 文件

如果你是协作者而不是仓库维护者，请先阅读：

1. [docs/collaborators/README.md](docs/collaborators/README.md)

## Important Documents

- [docs/README.md](docs/README.md)
  文档系统总入口。
- [docs/dev/README.md](docs/dev/README.md)
  开发者阅读入口。
- [docs/dev/tutorials/reusable-code-index.md](docs/dev/tutorials/reusable-code-index.md)
  可复用代码索引。AI 和开发者新增代码前，先看这里，优先复用。
- [docs/dev/tutorials/configs-directory-guide.md](docs/dev/tutorials/configs-directory-guide.md)
  `configs/` 目录结构与编辑边界说明。
- [docs/dev/tutorials/configs-command-guide.md](docs/dev/tutorials/configs-command-guide.md)
  `configs` 相关发现、验证和消费命令指南。
- [docs/collaborators/README.md](docs/collaborators/README.md)
  协作者阅读入口。
