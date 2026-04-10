# mmWave Smoke Test 简明操作手册

本文档面向需要执行板卡联调的协作者。

`smoke-test` 的目标很简单：确认当前 mmWave 板卡在加载指定 `cfg` 后，`data UART` 能持续输出可解析的数据包。

如果它通过，说明当前这套“板卡 + 固件 + cfg + 串口连接”至少具备最小可用性。

## 1. 使用前提

开始前请确认：

- 板卡已经上电，并通过 USB 连接到电脑
- 你当前位于仓库根目录
- 本地已经完成依赖安装；如未安装，先执行 `uv sync --dev`
- 你知道本次要使用的 `cfg`

当前仓库内置了两个可直接使用的 `cfg`：

- `baseline_pointcloud`
  推荐优先使用的低风险基线配置，对应 [configs/profile_3d.cfg](/Users/skd/Documents/vscode-projects/vassago/configs/profile_3d.cfg)
- `rd_candidate`
  风险较高的候选配置，对应 [configs/rd_phase1_uart.cfg](/Users/skd/Documents/vscode-projects/vassago/configs/rd_phase1_uart.cfg)

## 2. 推荐操作流程

推荐按下面顺序执行。

### 第一步：查看当前可见串口

```bash
uv run vassago firmware mmwave list-ports
```

这一步只负责列出当前电脑能看到的串口。

### 第二步：探测哪个端口更像 CLI / Data

```bash
uv run vassago firmware mmwave probe-ports
```

你会看到一张表，重点关注两列：

- `CLI Prompt`
  为 `yes` 说明这个端口更像 CLI 口
- `Valid Packets`
  数值较高说明这个端口更像 Data 口

命令末尾还会给出：

- `Suggested CLI port`
- `Suggested Data port`

如果这里两个角色都识别不出来，先不要继续反复跑 `smoke-test`，优先检查接线、供电和板卡状态。

### 第三步：执行 smoke test

最推荐先跑基线配置：

```bash
uv run vassago firmware mmwave smoke-test \
  --config-id baseline_pointcloud \
  --cli-port /dev/ttyXXX \
  --data-port /dev/ttyYYY \
  --no-interactive
```

说明：

- `--config-id baseline_pointcloud`：先上传仓库内置的基线 `cfg`
- `--cli-port`：用于发送 `cfg`
- `--data-port`：用于接收雷达输出数据
- `--no-interactive`：脚本化执行时建议显式关闭交互

如果你要使用自己的 `cfg` 文件，可以改成：

```bash
uv run vassago firmware mmwave smoke-test \
  --config /absolute/path/to/your.cfg \
  --cli-port /dev/ttyXXX \
  --data-port /dev/ttyYYY \
  --no-interactive
```

`--config` 和 `--config-id` 二选一，不要同时传。

## 3. 交互模式怎么用

如果你直接在终端里运行，并且没有把参数传全，`smoke-test` 默认会进入交互模式：

```bash
uv run vassago firmware mmwave smoke-test
```

此时程序会：

- 展示仓库内置 `cfg` 供你选择
- 自动探测候选串口
- 让你确认 CLI 口和 Data 口

如果你只是想监听数据、不上传 `cfg`，可以在交互选择时选 `Listen only (skip cfg upload)`。

## 4. 如何判断是否通过

运行结束后会输出 `Smoke Test Summary` 表。

重点看下面几项：

- `bytes_read`
  大于 `0` 说明 Data 口确实读到了数据
- `valid_packets`
  成功解析出的有效包数量
- `invalid_packets`
  无法正常解析的包数量
- `result`
  `PASS` 表示通过，`FAIL` 表示未通过

默认判定标准是：

- `valid_packets >= 3` 就算通过

也就是说，默认退出码含义为：

- `0`：通过
- `1`：数据读取完成了，但有效包不足，测试失败
- `2`：`cfg` 上传阶段就失败或超时

开始读到第一段数据时，程序可能会打印一段十六进制预览。这是正常现象，用来帮助你快速确认 Data 口确实有输出。

## 5. 常用参数

大多数情况下默认值够用，只需要关心下面几个参数：

- `--duration`
  监听时长，默认 `5.0` 秒
- `--min-packets`
  通过门槛，默认 `3`
- `--verbose`
  打开后会逐条打印解析到的 frame 编号
- `--cli-baudrate`
  默认 `115200`
- `--data-baudrate`
  默认 `921600`

如果你没有特殊固件要求，通常不需要改波特率。

## 6. 常见失败处理

### 情况 1：`probe-ports` 看不到明显的 CLI 提示，也没有数据输出

优先做这几件事：

- 重新插拔 USB 或重新上电
- 确认板卡驱动和串口权限正常
- 重新执行 `probe-ports`

### 情况 2：`cfg` 上传失败，输出里出现 `failed_command`

这通常说明：

- 当前 `cfg` 和板上固件不兼容
- 某条命令不被当前固件支持

建议先退回 `baseline_pointcloud` 验证基线链路，再决定是否继续调试自定义 `cfg`。

### 情况 3：`result = FAIL`

这说明串口读流程已经结束，但有效包数量没有达到门槛。优先检查：

- `data-port` 是否选对
- 板卡是否真的已经启动到会持续输出数据的状态
- 当前 `cfg` 是否已经成功下发

## 7. 一条最短可执行路径

如果你只想先验证“这块板子现在能不能出包”，直接按下面三条命令做：

```bash
uv run vassago firmware mmwave probe-ports
uv run vassago firmware mmwave smoke-test --config-id baseline_pointcloud --cli-port /dev/ttyXXX --data-port /dev/ttyYYY --no-interactive
echo $?
```

最后一个命令如果输出 `0`，说明这次 smoke test 通过。

如果你的机器遇到 `uv` 缓存目录权限问题，可以临时改用：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run vassago firmware mmwave smoke-test --help
```
