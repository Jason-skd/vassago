# RD Collection QC 实操说明

这篇文档写给执行采集、整理 session 和准备交接数据的人。

它只回答 3 个问题：

- 什么时候需要跑 QC
- 命令怎么执行
- 结果出来后下一步怎么做

如果你还没做过一次完整采集，先看 [rd_collection.md](rd_collection.md)。

## 1. 先分清两层 QC


- `quick QC`
  每次 take 结束后自动执行，决定这次 take 能不能进入 `Accept take`。
- `offline QC`
  面向整个 session `manifest.json` 的离线复核。它不会替代 live `quick QC`，而是补做一次 session 级检查。

实践里可以这样记：

- 采集当下，先看 `quick QC`
- 一轮 session 结束后，再跑 `offline-qc`

补充（背景采集 / `white_space` / `normal_activity`）：

- `white_space` / `normal_activity` 不走逐 take 的 `Accept take` 流程，因此**没有 live `quick QC` gate**
- 这两类 background session 的 QC 重点落在 offline 阶段（manifest 契约、连续采集记录；以及后续切片产物的校验）

仓库的 `pre-commit` 会自动执行一次全量 `offline-qc-all`，扫描 `data/collection/rd/sessions/` 下的全部 session manifest。手动先跑一遍当前 session 的 `offline-qc`，意义是更早发现问题；手动跑一遍 `offline-qc-all`，则可以完整复现 hook 的检查口径。

## 2. 最短执行路径

先确认你要检查的 session `manifest.json` 在哪里。当前目录结构通常长这样：

```text
data/collection/rd/sessions/<session_id>/
  manifest.json
  takes/
    take01/
      raw_uart.bin
```

背景采集（`white_space` / `normal_activity`）通常长这样：

```text
data/collection/rd/sessions/<session_id>/
  manifest.json
  background/
    background_raw_uart.bin
```

先检查当前这一个 session 时，直接运行：

```bash
uv run vassago collection rd offline-qc --manifest data/collection/rd/sessions/<20260426_000426_qdr_white_space>/manifest.json
```

这条命令会同时检查：

- `manifest.json` 顶层字段和 `config_snapshot` 是否还符合约定
- 所有 `accepted` take 的 `raw_uart.bin`、窗口信息和 quick-QC 结果是否还能离线重放通过

说明：

- 对于 `white_space` / `normal_activity` background 会话，先运行一次：

```bash
uv run vassago processing rd extract --manifest data/collection/rd/sessions/<20260426_000426_qdr_white_space>/manifest.json
```

- 这一步会生成：
  - `background/rd_segments_manifest.json`
  - `background/segments/<segment_id>/rd.npz`
- 当前 offline QC 会额外检查这份切片 index/manifest 与各个 `rd.npz` 是否完整、可重放且和 selection seed 对得上。

如果你想在提交前完整复现仓库 hook 的行为，再运行：

```bash
uv run vassago collection rd offline-qc-all
```

这条命令会扫描 `data/collection/rd/sessions/*/manifest.json`，并先输出一个总览的 `Offline QC Validation Summary`，再按 manifest 逐个展开明细。

## 3. 输出结果怎么判断

单 session 命令先看 `Offline QC Summary` 里的 `result`；全量命令先看 `Offline QC Validation Summary` 里的 `result`。

- `pass`
  当前没有 `error`，可以继续交接、提交或进入下一步处理。
- `pass_with_warnings`
  当前没有 `error`，但有 `warning`。先看 warning 是不是预期内的配置覆盖，再决定是否继续。
- `fail`
  当前至少有一个 `error`。先处理问题，不要急着提交或交接。

退出码规则也很简单：

- `0` 表示没有 `error`
- `1` 表示出现了 `error`

## 4. 失败后先怎么定位

先看每一条结果前缀里的 `plugin`、`code` 和 `take`。

最常见的是两类：

- `quick_qc:*`
  更像样本或 take 产物问题。优先检查对应 take 的 `raw_uart.bin`、结束打点和窗口字段。
- `metadata_qc:*`
  更像 manifest 契约问题。优先检查 `manifest.json` 顶层字段、`config_snapshot` 和 take 结构有没有缺字段或被手工改坏。
- `background_npz_qc:*`
  更像空背景切片产物问题。优先检查 `background/rd_segments_manifest.json`、segment `rd.npz` 文件以及 selection seed 对应的窗口记录。

可以先按这个顺序处理：

1. 确认 `raw_uart.bin` 还在，而且不是空文件。
2. 确认对应 take 里的 `raw_uart_path`、`capture_window`、`target_window`、`marked_window` 没缺。
3. 确认 `manifest.json` 顶层字段没有被手工删改。

## 5. 最常见的处理动作

### 情况 1：`quick_qc` 失败

优先考虑：

- 这次 take 本身质量不好，需要重采
- `raw_uart.bin` 丢了、为空，或者路径不对
- 结束打点和窗口信息没有正确写入

实践建议：

- 不要先手工改 `manifest.json` 试图“糊过去”
- 先保留当前 session 目录和 `raw_uart.bin`
- 能重采时优先重采对应 take 或重开一轮 session

### 情况 2：`metadata_qc` 失败

优先考虑：

- `manifest.json` 被手工改过
- 历史 session 不符合当前仓库契约
- 当前 session 的生成流程出了问题

实践建议：

- 不要盲目手改字段来压过 QC
- 如果这是当前代码刚生成的新 session，却仍然失败，把 `manifest` 路径和完整输出发给维护者

## 6. 推荐工作习惯

- 每轮 session 结束后，先对当前 session 手动跑一次 `offline-qc`
- 准备提交前，手动跑一次 `offline-qc-all`，确认和 `pre-commit` 一致
- 准备提交 session manifest 前，再看一次 `Offline QC Summary`
- 看到 `fail` 时，先保留现场，不要先删 `raw_uart.bin`
- 不确定 warning 是否正常时，把完整输出一并发给维护者
