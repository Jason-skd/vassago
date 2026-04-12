# RD Collection QC 使用指南

这篇文档是写给“要运行、排查或扩展 RD collection QC”的人看的。

它覆盖 3 件事：

- live capture 里的 `quick_qc` 是怎么工作的
- 离线 `offline-qc` 命令会检查什么
- 当结果是 `pass`、`pass_with_warnings` 或 `fail` 时，应该怎么理解

本文以当前仓库实现为准，主要对应：

- `src/vassago/collection/rd/quick_qc.py`
- `src/vassago/collection/rd/metadata_qc.py`
- `src/vassago/collection/rd/offline_qc.py`
- `src/vassago/collection/rd/qc_contract.py`
- `src/vassago/collection/rd/cli.py`

如果旧文档和本文冲突，以本文为准。

## 1. 先建立正确心智模型

当前 RD collection QC 分成两层：

- `quick_qc`
  - 作用在单次 take 的样本质量
  - 在 live capture 里直接决定这次 take 是否可以 accept
  - 也会被 `offline_qc` 重放，用于离线复查 accepted take
- `offline_qc`
  - 作用在整个 session manifest
  - 是 orchestrator，不是单个检查器
  - 会汇总多个 peer checks，目前至少包括：
    - `metadata_qc`
    - offline replay 的 `quick_qc`

一句话记忆：

- `quick_qc` 关心“这次 take 采得行不行”
- `metadata_qc` 关心“manifest contract 对不对”
- `offline_qc` 负责把这些检查串起来

## 2. live collection 里的 QC 是什么

当你运行：

```bash
uv run vassago collection rd run-session --manifest <manifest.json>
```

或者：

```bash
uv run vassago collection rd resume-session --manifest <manifest.json>
```

系统会在每次 take 结束后自动跑 `quick_qc`。

当前 live `quick_qc` 的 blocking 检查只有 3 类：

- 缺少结束标记
- 结束标记超出 `target_window + grace`
- 原始采集为空，或没有解析出 valid packet

如果 `quick_qc` 失败，当前 take 不会被 accept。

### 常见 reason code

- `missing_end_mark`
  没有记录到结束标记。
- `late_end_mark`
  结束标记超过了 `target_window.end_s + marked_window_end_grace_s`。
- `empty_capture`
  `raw_uart.bin` 长度为 0。
- `no_valid_packets`
  原始数据存在，但没有解析出有效 packet。

## 3. 离线 QC 怎么跑

对一个已经存在的 session manifest 运行：

```bash
uv run vassago collection rd offline-qc --manifest <manifest.json>
```

这个命令会做两组检查：

1. `metadata_qc`
   检查 manifest 顶层 contract、take-level contract、`config_snapshot` 结构，以及 top-level 和 snapshot 的 mirror / membership / default 对照关系。
2. offline replay `quick_qc`
   对所有 `status == accepted` 的 take，重新读取 `raw_uart.bin`，再跑一遍和 live capture 相同口径的 `quick_qc`。

## 4. `offline-qc` 输出怎么理解

当前 CLI 结果分 3 类：

- `pass`
  没有 `error`，也没有 `warn`。
- `pass_with_warnings`
  没有 `error`，但有 `warn`。
- `fail`
  至少有一个 `error`。

退出码规则：

- `0`
  没有 `error`
- `1`
  存在 `error`

这意味着：

- warning 不会让命令失败
- error 会直接让命令失败

## 5. 什么情况会是 warning

当前最典型的 warning 是：

- 顶层实际选择值和 `config_snapshot.defaults.*` 不一致，但仍然合法

例如：

- `radar_id` 与 `config_snapshot.defaults.radar_id` 不一致
- `firmware_id` 与 `config_snapshot.defaults.firmware_id` 不一致
- `environment` 与 `config_snapshot.defaults.environment` 不一致，但仍然属于 allowed options

这类 warning 的含义不是“manifest 坏了”，而是：

- 本次 session 覆盖了 profile 默认值
- 这个偏离需要被离线 QC 显式暴露出来

## 6. 什么情况会是 error

典型 error 包括：

- manifest 顶层缺少公共 contract 字段
- top-level `gesture_options` / `environment_options` / `batch_size` 与 snapshot 不一致
- `gesture` 或 `environment` 不属于 snapshot 提供的 allowed options
- accepted take 缺少 `raw_uart_path`、`capture_window`、`target_window`
- accepted take 对应的 `raw_uart.bin` 不存在
- accepted take 重放 `quick_qc` 后出现 blocking finding

如果是当前代码新生成的 manifest，默认不应该因为 contract 缺失而报错。

如果你看到了这类 error，优先怀疑：

- manifest 是手工改坏的
- take artifact 丢了
- accepted take 的窗口字段不完整
- 历史 manifest 不符合当前 contract

当前仓库不要求为旧 manifest 做兼容行为。

## 7. 最常用的排查顺序

### 场景 1：`offline-qc` 直接 fail

先做：

```bash
uv run vassago collection rd offline-qc --manifest <manifest.json>
```

看输出里的：

- `plugin`
- `code`
- `field`
- `take`

经验上可以这样判断：

- `metadata_qc:*`
  先看 manifest 顶层字段和 `config_snapshot`
- `quick_qc:*`
  先看 take 的 `raw_uart_path`、窗口字段和对应原始数据

### 场景 2：新 manifest 应该合法，但出现 metadata error

优先检查 manifest 顶层是否有这些字段：

- `batch_size`
- `gesture_options`
- `environment_options`
- `takes`

再检查 `config_snapshot` 是否有这些字段：

- `batch_size`
- `runtime.*`
- `defaults.*`
- `serial.*`
- `options.*`
- `gesture_target_durations`

### 场景 3：accepted take 在离线重放时失败

优先检查：

- `raw_uart_path` 指向的文件是否真的存在
- `capture_window` / `target_window` / `marked_window` 是否完整
- `raw_uart.bin` 是否为空

如果要进一步确认原始数据是否真有 packet，可参考：

```bash
uv run pytest tests/test_mmwave_protocol.py
```

以及代码里的：

- `collection.rd.capture.summarize_raw_capture()`
- `firmware.mmwave.protocol`

## 8. 如果你要扩展 QC，应该改哪里

如果你要做的是：

- 新增样本质量规则
  先改 `quick_qc.py`
- 新增 manifest contract 校验
  先改 `metadata_qc.py`
- 新增一个新的 offline peer check
  先改 `offline_qc.py`，并复用 `qc_contract.py` 的 finding / report 模型

不要做的事：

- 在新 CLI 里自己再发明一套 QC finding schema
- 在多个模块里各写一份 manifest contract 字段清单
- 把 live `quick_qc` 逻辑复制一份到 offline

## 9. 最小验收建议

如果你改了 QC 相关代码，最少跑这些：

```bash
uv run pytest tests/test_collection_quick_qc.py
uv run pytest tests/test_collection_offline_qc.py
uv run pytest tests/test_collection_cli.py
```

如果改动涉及 manifest 写入，再补：

```bash
uv run pytest tests/test_collection_session.py
```

如果改动较大，直接跑：

```bash
uv run pytest
```
