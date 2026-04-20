# RD processing: `extract` / `extract-all` 命令指南

本文档固定 `vassago processing rd` 下的离线导出命令使用方式。

范围：

- `raw_uart.bin -> rd.npz` 的离线导出
- 单个 manifest 导出与全量导出（按 sessions root 扫描）

不包含：

- RD collection 的采集与 QC 使用说明（协作者文档维护在 collaborators 侧）
- 训练侧 loader 的消费约定（训练模块文档另行维护）

## 背景与目标

仓库对 source-of-truth 的分层已经明确：

- capture truth：`raw_uart.bin`
- ML-facing truth：`rd.npz`

`rd.npz` 是训练侧 canonical sample，它不等同于 debug bundle，也不是 manifest 镜像。

字段最小集合、边界与取舍的讨论留痕位于：

- `docs/dev/context/20260420_training_rd_npz_contract.md`

本教程只描述“如何导出”，不重复 contract 细节。

## 命令入口

`vassago` 是本仓库 `pyproject.toml` 注册的脚本入口。

RD 离线处理命令树：

- `vassago processing rd extract`
- `vassago processing rd extract-all`

## `extract`: 导出单个 manifest

用途：从一个 `manifest.json` 中挑选 accepted takes，逐个导出 `rd.npz`。

### 参数

- `--manifest PATH`（必填）
  - 指向一个 collection session 的 `manifest.json`
- `--take-id TAKE_ID`（可选）
  - 只导出某一个 accepted take
- `--output PATH`（可选）
  - 显式指定输出路径
  - 约束：只有在同时指定 `--take-id` 时才允许使用
- `--overwrite / --no-overwrite`（默认 `--no-overwrite`）
  - 若目标 `rd.npz` 已存在，是否覆盖

### 默认输出路径

- 不传 `--output` 时，默认写到该 take 的 `raw_uart.bin` 同目录下，文件名固定为 `rd.npz`
- 因为一个 accepted take 对应一个 `raw_uart.bin`，因此也固定是一份 `rd.npz`

### 行为与退出码

- 若 manifest 中没有任何可导出的 accepted take，退出码为 **1**
- 参数组合非法（例如 `--output` 未配 `--take-id`），会以参数错误退出

### 示例

导出一个 manifest 下所有 accepted takes：

```bash
uv run vassago processing rd extract --manifest data/collection/rd/sessions/<session_id>/manifest.json
```

只导出一个 take：

```bash
uv run vassago processing rd extract --manifest data/collection/rd/sessions/<session_id>/manifest.json --take-id take01
```

导出一个 take 到显式路径：

```bash
uv run vassago processing rd extract --manifest data/collection/rd/sessions/<session_id>/manifest.json --take-id take01 --output /tmp/rd.npz
```

## `extract-all`: 全量导出（扫描 sessions root）

用途：扫描一个 sessions root 下所有 session manifest，批量导出所有 accepted takes 的 `rd.npz`。

这类命令的 CLI 风格与 `collection rd offline-qc-all` 保持一致：固定 summary 输出，并将失败转换成稳定 exit code。

### 参数

- `--sessions-root PATH`（默认 `data/collection/rd/sessions`）
  - 被扫描目录，期望结构为：
    - `<sessions_root>/<session_id>/manifest.json`
- `--overwrite / --no-overwrite`（默认 `--no-overwrite`）

### 输出与退出码

命令会打印：

- `checked_manifests`: 扫描到并尝试处理的 manifest 数
- `written_artifacts`: 实际写出的 `rd.npz` 文件数（按 take 计数）
- `failed_manifests`: 处理失败的 manifest 数

退出码规则：

- 如果 **未发现任何** session manifest，退出码为 **1**
- 如果存在 **任何失败** 的 manifest，退出码为 **1**
- 否则退出码为 **0**

### 示例

在默认 sessions root 上全量导出：

```bash
uv run vassago processing rd extract-all
```

对一个临时 sessions root 全量导出（例如本地回归数据）：

```bash
uv run vassago processing rd extract-all --sessions-root /path/to/sessions
```

## 常见问题

### 1) 为什么 `extract` 的 `--output` 需要 `--take-id`？

因为 batch 导出是“一个 accepted take 一份 `rd.npz`”。如果不指定 take，`--output` 没有稳定的一对一映射目标。

### 2) `rd.npz` 里会包含哪些字段？

字段集合以 `docs/dev/context/20260420_training_rd_npz_contract.md` 为准；实现层会写出 `schema_version`、主数据 `rd` 以及训练必需的 metadata 与窗口标签。

### 3) 为什么全量导出会把“没有 accepted takes 的 manifest”也算进 `checked_manifests`？

`checked_manifests` 表达的是“被扫描并尝试处理的 manifest 数”，而不是“产出文件的 manifest 数”。这能让全量跑批在日志里稳定表达扫描范围。

