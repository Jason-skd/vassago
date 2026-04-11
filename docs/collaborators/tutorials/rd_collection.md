# RD Collection 简明操作手册

本文档面向需要执行毫米波手势数据采集的协作者。

`collection` 的目标是把一次采集会话拆成可恢复、可验收、可追踪的一组 take，并在每次接受样本时保存：

- `raw_uart.bin`
- 本次 take 的接收状态
- 固定 5 秒 `capture_window`
- 配置定义的 `target_window`
- 协作者按键打点得到的 `marked_window`

如果你已经完成板卡联调，并且已经创建或准备创建 session，可以按本文档执行采集。

## 1. 使用前提

开始前请确认：

- 板卡已经上电，并通过 USB 连接到电脑
- 你当前位于仓库根目录
- 本地已经完成依赖安装；如未安装，先执行 `uv sync --dev`
- 当前板卡已经通过 `smoke-test`
- 你知道本轮要使用哪个 collection config

如果你还没有完成板卡联调，请先阅读：

- [mmwave_smoke_test.md](/Users/skd/Documents/vscode-projects/vassago/docs/collaborators/tutorials/mmwave_smoke_test.md)

## 2. 先确认 collection config

先看仓库当前提供了哪些采集配置：

```bash
uv run vassago collection rd list-configs
```

当前仓库内置的默认 profile 是：

- `rd_phase1_default`
  对应 [rd_phase1_default.toml](/Users/skd/Documents/vscode-projects/vassago/configs/collection/rd/rd_phase1_default.toml)

这个 profile 会定义：

- 可选动作
- 可选速度
- 可选环境
- 默认手别、距离、角度
- 串口波特率
- 固定 5 秒采集窗口
- 每个 `gesture + speed` 对应的 `target_window`

## 3. 第一次创建 session

如果你还没有创建 session，最简单的方式是直接用交互模式：

```bash
uv run vassago collection rd init-session
```

程序会依次引导你选择或输入：

- collection config
- gesture
- speed
- 串口
- `subject_name`
- `hand`
- `distance_m`
- `angle_deg`
- `environment`
- `operator_name`
- `note`
- `radar_id`
- `firmware_id`

注意：

- 交互模式下，`operator_name` 现在必须手动输入，不会自动带默认值
- `gesture`、`speed`、`environment` 不是自由输入，而是从配置里选择
- session 创建成功后，会生成一个 `manifest.json`

如果你已经知道所有参数，也可以用非交互模式：

```bash
uv run vassago collection rd init-session \
  --config-id rd_phase1_default \
  --subject-name skd \
  --gesture swipe_left \
  --speed normal \
  --environment office_lab \
  --operator-name your_name \
  --radar-id rd_aop_01 \
  --firmware-id rd_phase1_uart \
  --cli-port /dev/ttyXXX \
  --data-port /dev/ttyYYY \
  --no-interactive
```

## 4. 已有 session 怎么开始采集

如果你已经创建过 session，最简单的方式是：

```bash
uv run vassago collection rd run-session
```

在交互终端里运行时，程序会：

- 列出所有未完成 session
- 让你选择一个 session 继续
- 重新下发该 session 绑定的 `cfg`
- 从下一个未接受的 take 开始采集

如果你已经知道 manifest 路径，也可以直接指定：

```bash
uv run vassago collection rd run-session \
  --manifest data/collection/rd/sessions/<session_id>/manifest.json
```

如果你只是想先看看有哪些 session 可以恢复：

```bash
uv run vassago collection rd list-sessions
```

## 5. 采集时怎么操作

进入 `run-session` 后，每个 take 都按下面流程执行。

### 第一步：选择是否开始当前 take

界面会显示当前状态，包括：

- 当前是第几个 take
- 已接受多少个 take
- 还剩多少个 take
- 当前 `target_window`

然后你会看到两个选项：

- `Start capture`
- `Leave session`

如果只是暂时不想继续，直接选 `Leave session`。当前 session 会保留，后面可以继续恢复。

### 第二步：在 5 秒窗口内做动作并打点

开始采集后：

- 程序会读取固定 5 秒的 data UART 数据
- 你需要在动作开始时按一次 `m`
- 在动作结束时再按一次 `m`

这两次按键会生成本次 take 的 `marked_window`。

如果你没有按满两次 `m`，或者两次打点无效，那么：

- `marked_window` 会被记为 `null`

### 第三步：看采集结果并决定是否接受

采集结束后，程序会显示本次 take 的摘要，包括：

- `bytes_read`
- `valid_packets`
- `invalid_packets`
- `first_frame`
- `last_frame`
- `frame_gaps`
- `marked_window`

然后你会看到三个选项：

- `Accept take`
- `Retry take`
- `Quit session`

含义分别是：

- `Accept take`
  保存本次采集结果，并进入下一个 take
- `Retry take`
  丢弃本次结果，重新采当前 take
- `Quit session`
  立即退出，后续再恢复这个 session

## 6. 接受一个 take 之后会发生什么

当你选择 `Accept take` 后，系统会：

- 把本次原始数据保存为 `raw_uart.bin`
- 更新当前 take 的 `status`
- 写入 `accepted_at`
- 写入 `raw_uart_path`
- 写入 `marked_window`
- 更新 session 的 `manifest.json`

典型目录结构如下：

```text
data/collection/rd/sessions/<session_id>/
  manifest.json
  takes/
    take01/
      raw_uart.bin
    take02/
      raw_uart.bin
```

## 7. 如何判断这次 session 采集正常

至少满足下面几点，才算正常：

- `run-session` 能成功进入采集，而不是在配置阶段报错
- 采集过程中 `bytes_read` 大于 `0`
- `valid_packets` 不是长期为 `0`
- 你接受一个 take 后，`raw_uart.bin` 确实生成
- `manifest.json` 被更新
- 下次重新运行 `run-session` 时，会从下一个未完成 take 继续

如果本次 session 的所有 take 都被接受，session 会进入完成状态。

## 8. 最短可执行路径

如果你已经有一个 session，只想尽快继续采集，直接按下面顺序做：

```bash
uv run vassago collection rd list-sessions
uv run vassago collection rd run-session
```

进入后：

1. 选一个未完成 session
2. 选 `Start capture`
3. 做动作时按两次 `m`
4. 看摘要
5. 选 `Accept take` 或 `Retry take`

## 9. 常见失败处理

### 情况 1：`run-session` 一开始就失败

优先检查：

- `cli_port` 和 `data_port` 是否还是当前真实串口
- 板卡是否重新上电后端口名发生变化
- 当前板卡是否还能通过 `smoke-test`

如果不确定，先重新跑：

```bash
uv run vassago firmware mmwave probe-ports
uv run vassago firmware mmwave smoke-test --config-id baseline_pointcloud
```

### 情况 2：能进入采集，但 `bytes_read = 0`

优先检查：

- `data_port` 是否选错
- 雷达是否真的已经启动到输出状态
- 当前 `cfg` 是否和固件兼容

### 情况 3：`marked_window` 总是 `null`

优先检查：

- 采集期间是否真的按了两次 `m`
- 当前终端是不是交互式 TTY
- 两次打点顺序是否正确

### 情况 4：中途退出了，还想继续

直接重新运行：

```bash
uv run vassago collection rd run-session
```

然后重新选择刚才那个未完成 session 即可。

## 10. 对协作者最重要的执行原则

- 先完成 `smoke-test`，再做 collection
- 同一轮 session 尽量保持 `subject_name`、环境和动作配置一致
- `Accept take` 前，先看摘要是否明显异常
- 不确定时优先 `Retry take`，不要勉强接受明显坏样本
- 中途退出没关系，session 可以恢复
