# Vassago Developer Quickstart

#python #uv #dev-workflow #quickstart

---

## Navigation

> [!tip] 基础篇
> [[#1. Prerequisites|前置条件]] | [[#2. Project Setup|项目初始化]] | [[#3. Daily Commands|日常指令]]

> [!info] 进阶篇
> [[#4. Code Quality|代码质量]] | [[#5. Git Hooks|Git Hooks]]

> [!example] 实用篇
> [[#6. Cheat Sheet|速查表]]

---

## 1. Prerequisites

- Python >= 3.14(项目 `.python-version` 已锁定)
- [uv](https://docs.astral.sh/uv/) — 包管理 & 虚拟环境
- [Lefthook](https://github.com/evilmartians/lefthook) — Git hooks 管理

```zsh
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装 lefthook
brew install lefthook
```

---

## 2. Project Setup

```zsh
# 克隆后一键初始化
uv sync
lefthook install
```

> [!tip] `uv sync` 会自动创建 `.venv`, 安装所有依赖(含 dev 组)

---

## 3. Daily Commands

### 3.1 运行测试

```zsh
uv run pytest
```

快速模式(遇到第一个失败即停):

```zsh
uv run pytest -x -q
```

### 3.2 添加依赖

```zsh
# 生产依赖
uv add <package>

# 开发依赖
uv add --group dev <package>
```

### 3.3 运行项目代码

```zsh
uv run python -m vassago
```

---

## 4. Code Quality

### 4.1 格式化

```zsh
uv run ruff format .
```

### 4.2 Lint 检查 & 自动修复

```zsh
uv run ruff check --fix .
```

> [!info] 项目启用了 `ALL` 规则集, 具体豁免见 `pyproject.toml` 的 `[tool.ruff.lint]`

### 4.3 一步到位

```zsh
uv run ruff format . && uv run ruff check --fix .
```

---

## 5. Git Hooks

项目通过 Lefthook 在 `pre-commit` 阶段自动执行:

| Hook | 作用 |
|------|------|
| `format` | ruff format 格式化暂存文件 |
| `lint` | ruff check --fix 修复暂存文件 |
| `test` | pytest -x -q 跑测试 |

> [!warning] 提交前测试不过会阻止 commit, 确保本地测试通过再提交

跳过 hooks(紧急情况):

```zsh
git commit --no-verify -m "wip"
```

---

## 6. Cheat Sheet

| 场景 | 指令 |
|------|------|
| 初始化环境 | `uv sync` |
| 跑测试 | `uv run pytest` |
| 格式化 | `uv run ruff format .` |
| Lint | `uv run ruff check --fix .` |
| 加依赖 | `uv add <pkg>` |
| 加 dev 依赖 | `uv add --group dev <pkg>` |
| 安装 hooks | `lefthook install` |
