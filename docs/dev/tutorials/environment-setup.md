# 开发者环境配置手册

本文档用于帮助新开发者在本地完成 `vassago` 项目的开发环境初始化，并验证格式化、静态检查、测试、Git Hook 等开发链路可正常运行。

## 1. 常用指令总览

在正式开始环境配置前，建议先阅读：

- [README.md](../../../README.md)
- [../README.md](../README.md)
- [development-workflow.md](development-workflow.md)

建议先熟悉下面这些日常高频命令。

| 场景 | 命令 |
| --- | --- |
| 同步开发依赖 | `uv sync --dev` |
| 查看项目 Python 版本 | `uv run python --version` |
| 运行 lint | `uv run ruff check .` |
| 运行类型检查 | `uv run pyright` |
| 自动格式化 | `uv run ruff format .` |
| 检查格式是否符合要求 | `uv run ruff format --check .` |
| 运行全部测试 | `uv run pytest` |
| 只跑受改动影响的测试 | `uv run pytest --testmon` |
| 运行测试，但不裁剪测试集合，仅按失败概率排序 | `uv run pytest --testmon-noselect` |
| 明确关闭 testmon | `uv run pytest --no-testmon` |
| 安装 Git hooks | `lefthook install` |
| 手动执行 pre-commit hook | `lefthook run pre-commit` |
| 验证包是否可导入 | `uv run python -c "import vassago; print(vassago.hello())"` |

如果遇到 `uv` 缓存目录权限问题，可以临时改用：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --dev
```

同理，手动执行 hook 时也可以这样传递缓存目录：

```bash
UV_CACHE_DIR=/tmp/uv-cache lefthook run pre-commit
```

## 2. 项目概览

当前仓库是一个基于 Python 的库项目，依赖管理与虚拟环境统一使用 `uv`。

从仓库配置可以确认以下约束：

- Python 版本要求：`>=3.14`
- 项目根目录存在 `.python-version`，当前固定为 `3.14`
- 开发依赖通过 `pyproject.toml` 中的 `dev` dependency group 管理
- 当前已配置开发工具：
  - `ruff`
  - `pyright`
  - `pytest`
  - `pytest-testmon`
  - `lefthook`

## 3. 前置要求

在开始之前，请确保你的本地环境满足以下条件：

- 已安装 `git`
- 已安装 `uv`
- 已安装 `lefthook`
- 可以使用 Python `3.14`
- 建议使用 VS Code 进行开发

### 3.1 安装 uv

如果你尚未安装 `uv`，可以参考官方安装文档：

- 官方安装说明：https://docs.astral.sh/uv/getting-started/installation/

常见安装方式如下。

macOS（Homebrew）：

```bash
brew install uv
```

macOS / Linux（官方安装脚本）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows（PowerShell）：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安装完成后，建议先确认 `uv` 可用：

```bash
uv --version
```

### 3.2 安装 lefthook

如果你尚未安装 `lefthook`，可以参考官方安装文档：

- 官方仓库：https://github.com/evilmartians/lefthook

常见安装方式如下。

macOS（Homebrew）：

```bash
brew install lefthook
```

Go：

```bash
go install github.com/evilmartians/lefthook@latest
```

安装完成后，建议先确认 `lefthook` 可用：

```bash
lefthook version
```

## 4. 获取代码

如果你还没有本地仓库，请先克隆项目：

```bash
git clone <your-repo-url>
cd vassago
```

如果仓库已经存在，只需要进入项目根目录：

```bash
cd vassago
```

## 5. 安装 Python 与项目依赖

### 5.1 安装 Python 3.14

项目要求 Python `3.14`。如果本机尚未安装，可以使用 `uv` 安装：

```bash
uv python install 3.14
```

安装后，可用以下命令查看可用解释器：

```bash
uv python list
```

### 5.2 同步开发依赖

在项目根目录执行：

```bash
uv sync --dev
```

这条命令会完成以下工作：

- 创建或更新本地虚拟环境 `.venv`
- 按 `uv.lock` 安装锁定依赖
- 安装开发依赖组中的工具

如果你只想运行项目命令，通常不需要手动激活虚拟环境，直接使用 `uv run` 即可。

如果你希望手动激活虚拟环境，可使用：

macOS / Linux：

```bash
source .venv/bin/activate
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
```

## 6. 配置 Git Hooks（lefthook）

项目已经在根目录提供了 `.lefthook.yaml`，用于接管 `pre-commit` 流程。完成依赖安装后，建议立刻执行：

```bash
lefthook install
```

执行成功后，Git 的 `pre-commit` hook 会被安装到当前仓库。之后每次提交前，仓库会自动执行以下动作：

- `uv run ruff format {staged_files}`
- `uv run ruff check --fix {staged_files}`
- `uv run pyright`
- `uv run pytest --testmon || [ $? -eq 5 ]`
- 对暂存区中的 `data/collection/rd/sessions/*/manifest.json` 逐个执行 `uv run vassago collection rd offline-qc --manifest <manifest>`

这里的行为可以概括为：

- 对暂存区中的 Python 文件做自动格式化
- 对暂存区中的 Python 文件执行 lint，并自动修复可修复问题
- 对暂存区中的 RD collection session manifest 做离线 QC，阻止带 `error` 的 session 数据被直接提交
- 对整个项目执行一次 `pyright` 类型检查，确保命令行结果与 VS Code Pylance 基本对齐
- 对整个项目调用一次 `pytest-testmon`，由 `testmon` 自己选择受改动影响的测试
- 如果当前仓库还没有测试、`pytest` 返回退出码 `5`，hook 不会因此阻塞提交

这里特意没有把 `ruff format` 和 `ruff check --fix` 改成全仓执行，因为它们会直接修改文件。提交前只处理暂存区中的 Python 文件，可以避免顺手改动未提交主题之外的文件。

如果你想在提交前手动演练一次 hook，可以执行：

```bash
lefthook run pre-commit
```

如果当前没有已暂存的 Python 文件，命令会直接跳过对应步骤，这是正常现象。

同理，如果当前没有已暂存的 RD session `manifest.json`，`offline-qc` 这一步也会自动跳过。

## 7. 验证开发环境

完成依赖同步和 hook 安装后，建议按顺序运行以下命令，确认开发链路正常。

### 7.1 确认 Python 版本

```bash
uv run python --version
```

预期应为 `Python 3.14.x`。

### 7.2 运行静态检查

```bash
uv run ruff check .
```

### 7.3 运行类型检查

```bash
uv run pyright
```

这条命令应尽量与 VS Code 中的 Pylance 检查结果保持一致。如果编辑器里出现新的类型错误，优先确认 `uv run pyright` 是否也能复现。

### 7.4 检查代码格式

```bash
uv run ruff format --check .
```

### 7.5 运行测试

```bash
uv run pytest
```

### 7.6 验证 testmon 链路

```bash
uv run pytest --testmon
```

说明：

- 当前仓库可能暂时没有测试用例
- 如果输出类似 `collected 0 items`，但命令本身可以正常执行，说明测试环境和 `testmon` 插件链路已经打通
- 当没有测试被收集时，`pytest` 和 `pytest --testmon` 都可能返回退出码 `5`

## 8. pytest-testmon 使用说明

`pytest-testmon` 的作用是根据源码变更和历史测试数据，优先选择受影响的测试执行，从而缩短本地回归时间。

### 8.1 testmon 生成什么数据

首次运行下面命令后，仓库根目录会生成或更新 `.testmondata`：

```bash
uv run pytest --testmon
```

这个文件用于记录测试与源码之间的关联关系。之后再次运行 `--testmon` 时，插件会基于该文件挑选受影响的测试。

### 8.2 常用运行方式

运行全部测试，不使用 testmon：

```bash
uv run pytest
```

只运行受影响的测试，并更新 `.testmondata`：

```bash
uv run pytest --testmon
```

不裁剪测试集合，但根据 testmon 的分析结果优先执行更可能失败的测试：

```bash
uv run pytest --testmon-noselect
```

明确关闭 testmon：

```bash
uv run pytest --no-testmon
```

### 8.3 在本项目中的推荐用法

建议本地开发时按下面的方式使用：

- 开发中快速回归：`uv run pytest --testmon`
- 提交前兜底检查：`uv run pytest`
- 依赖关系变化较大、怀疑 testmon 数据失真时：先跑一次完整 `uv run pytest`，再继续使用 `--testmon`

### 8.4 与 lefthook 的关系

当前仓库的 `pre-commit` 已经集成：

```bash
uv run pytest --testmon || [ $? -eq 5 ]
```

这意味着：

- 日常提交默认会调用一次全局 `pytest --testmon`，再由 `testmon` 选择受改动影响的测试
- 在仓库测试尚少的早期阶段，即使没有测试文件，也不会让提交失败

## 9. VS Code 推荐配置

仓库已经提供了基础 VS Code 配置：

- `.vscode/settings.json`
- Python 文件默认格式化器为 `charliermarsh.ruff`
- 保存时自动格式化

建议在 VS Code 中安装以下扩展：

- Python
- Ruff

打开项目后，建议确认解释器指向项目虚拟环境：

- macOS / Linux：`.venv/bin/python`
- Windows：`.venv\Scripts\python.exe`

如果你已经执行过 `uv sync --dev`，通常 VS Code 会自动识别 `.venv`。

## 10. 日常开发建议

一个推荐的最小工作流如下：

1. `uv sync --dev`
2. `lefthook install`
3. 开发代码
4. `uv run pytest --testmon`
5. `uv run ruff check .`
6. `uv run ruff format .`
7. `git add ...`
8. `git commit`

## 11. 常见问题

### 11.1 本机 `python3` 不是 3.14，是否有影响？

通常没有影响。项目开发应以 `uv run` 和 `.venv` 中的解释器为准，而不是系统自带的 `python3`。

建议优先使用：

```bash
uv run python --version
```

而不是：

```bash
python3 --version
```

### 11.2 `uv sync --dev` 失败怎么办？

优先检查以下问题：

- `uv` 是否安装成功
- 本机是否已经安装或允许 `uv` 下载 Python 3.14
- 网络是否可以访问 Python 和包索引下载源
- 当前目录是否确实位于项目根目录

如果是缓存目录权限问题，可以临时指定缓存目录后重试：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --dev
```

### 11.3 `lefthook install` 失败怎么办？

优先检查以下问题：

- 当前目录是否位于 Git 仓库根目录
- `lefthook` 是否已正确安装
- 当前用户是否对仓库的 `.git/hooks` 目录有写权限

安装完成后，可以用下面命令手动验证 hook 配置：

```bash
lefthook run pre-commit
```

### 11.4 VS Code 没有自动格式化怎么办？

请检查：

- 是否安装了 Ruff 扩展
- 当前打开的是整个仓库根目录，而不是单个文件
- VS Code 解释器是否已经切换到 `.venv`

### 11.5 `pytest --testmon` 没有跑任何测试，是不是坏了？

不一定。

常见原因包括：

- 当前仓库本身还没有测试用例
- 最近的代码变更没有命中任何已知测试依赖
- `.testmondata` 还没有足够的历史数据

如果你需要完全确认当前状态，直接运行：

```bash
uv run pytest
```

## 12. 完成标准

当下面几条都成立时，可以认为本地开发环境配置完成：

- `uv sync --dev` 成功执行
- `lefthook install` 成功执行
- `uv run python --version` 显示 `3.14.x`
- `uv run ruff check .` 成功
- `uv run ruff format --check .` 成功
- `uv run pytest` 能正常启动并执行测试发现流程
- `uv run pytest --testmon` 能正常启动并执行 testmon 流程

完成以上步骤后，你就可以开始在本仓库中继续开发、补充测试和迭代文档。
