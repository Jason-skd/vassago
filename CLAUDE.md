# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **维护卡片**
> - 基于 commit: `7a99aa6` (init commit)
> - 本文件应时刻保持**简洁、逻辑清晰、必要**，更新时先 `git diff <上次commit>..HEAD` 做增量更新，并考虑剪枝
> - 每次完成功能后附上建议的 commit message
> - 每次更新时同步维护下方 docs 索引

## 语言约定

- 所有符号使用半角字符(comment / docstring / docs...)
- comment / docstring 用中文
- print / logger / error message 用英文(面向用户)

## 技术栈

- Python >=3.14, 包管理: uv, 构建后端: uv_build
- Lint & Format: ruff (启用 ALL 规则集, 豁免见 `pyproject.toml [tool.ruff.lint]`)
- 测试: pytest
- Git hooks: lefthook (pre-commit 自动 format → lint → test)

## 常用命令

```zsh
uv sync                              # 初始化环境
uv run pytest                        # 跑全部测试
uv run pytest -x -q                  # 快速模式, 首个失败即停
uv run pytest tests/test_foo.py::test_bar  # 跑单个测试
uv run ruff format .                 # 格式化
uv run ruff check --fix .            # lint 检查 & 自动修复
```

## 项目结构

```
src/vassago/     # 主包源码
tests/           # 测试 (文件命名 test_*.py)
docs/            # 文档 (Obsidian 风格)
```

## Ruff 要点

- isort: `force-single-line = true` — 每个 import 独占一行
- 测试文件豁免: assert / magic value / 类型注解 / docstring 等 (详见 `pyproject.toml per-file-ignores`)
- docstring 风格: D211 (类前无空行) + D212 (摘要在首行)

## Docs 索引

| 文件 | 概述 |
|------|------|
| `docs/developer_quickstart.md` | 开发环境搭建、日常命令、Git hooks 使用的快速上手指南 |