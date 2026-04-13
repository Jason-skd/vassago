# RD Collection 简明操作手册

本文档面向需要执行毫米波手势数据采集的协作者。

`collection` 的目标是把一次采集会话拆成可恢复、可验收、可追踪的一组 take。当前版本会在 session 创建时先落一份 `manifest.json`，其中包含顶层公共字段和完整 `config_snapshot`；只有你明确接受样本后，才会补写正式 take 内容：

- `raw_uart.bin`
- 当前 take 的 `status`
- 本次真实 `capture_window`
- 本次运行时生成的 `target_window`
- 本次 `marked_window`

如果你已经完成板卡联调，并且已经创建或准备创建 session，可以按本文档执行采集。

## 1. 使用前提

开始前请确认：

- 板卡已经上电，并通过 USB 连接到电脑
- 你当前位于仓库根目录
- 本地已经完成依赖安装；如未安装，先执行 `uv sync --dev`
- 当前板卡已经通过 `smoke-test`
- 你知道本轮要使用哪个 collection profile

如果你还没有完成板卡联调，请先阅读：

- [mmwave_smoke_test.md](mmwave_smoke_test.md)

## 2. 先确认 collection profile

先看仓库当前提供了哪些采集 profile：

```bash
uv run vassago collection rd list-configs
```

当前仓库内置的默认 profile 是：

- `rd_phase1_default`
  对应 [../../../configs/collection/rd/profiles/rd_phase1_default.toml](../../../configs/collection/rd/profiles/rd_phase1_default.toml)

当前配置分成两层：

- 仓库级 baseline：[`global.toml`](../../../configs/collection/rd/global.toml)
  提供固定倒计时、采集窗口、结束键、串口默认波特率等稳定参数。
- 单轮采集 profile：[`rd_phase1_default.toml`](../../../configs/collection/rd/profiles/rd_phase1_default.toml)
  提供本轮动作列表、环境列表、默认手别/距离/角度，以及每个 `gesture` 的 `target_window_duration_s`。

对协作者最重要的是：

- 现在没有 `speed` 字段
- `target_window` 不再在配置里写死起止时间
- 采集时你只需要关注倒计时、`GO` 和结束按键

## 3. 第一次创建 session

如果你还没有创建 session，最简单的方式是直接用交互模式：

```bash
uv run vassago collection rd init-session
```

程序会依次引导你选择或输入：

- collection profile
- `gesture`
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

- 交互模式下，`operator_name` 必须手动输入，不会自动带默认值
- `gesture`、`environment` 不是自由输入，而是从 profile 里选择
- session 创建成功后，会生成一个 `manifest.json`
- `manifest.json` 顶层会直接写入本次 session 的公共字段，例如 `gesture`、`firmware_config_id`、`gesture_options`、`environment_options`、串口信息
- `config_snapshot` 会同时保留本次生效 collection config 的完整镜像，供后续追溯和离线 QC 使用

如果你已经知道所有参数，也可以用非交互模式：

```bash
uv run vassago collection rd init-session \
  --config-id rd_phase1_default \
  --subject-name skd \
  --gesture wave \
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
- 倒计时长度
- 本次动作的 `target_window_duration`
- 当前结束键

然后你会看到两个选项：

- `Start capture`
- `Leave session`

如果只是暂时不想继续，直接选 `Leave session`。当前 session 会保留，后面可以继续恢复。

### 第二步：等待固定倒计时和 `GO`

开始采集后：

- 程序会先进入固定倒计时
- `GO` 固定在倒计时结束时出现
- `capture_window` 可能已经在后台提前开始，但这部分对协作者是隐藏的

协作者不要去推测后台窗口位置，只需要按界面提示等待 `GO`。

### 第三步：在 `GO` 后做动作，并在结束时按一次结束键

当前版本里：

- `target_window` 会在 `GO` 时自动开始
- `marked_window.start_s` 也会自动跟着开始
- 你只需要在动作结束时按一次结束键

默认结束键来自 [`global.toml`](../../../configs/collection/rd/global.toml)，当前默认是：

- `space`

也就是说，当前不再需要像旧流程那样按两次 `m`。

### 第四步：先过 quick QC，再做人为决定

采集结束后，程序会先做一轮最小 quick QC。

当前 quick QC 至少会检查：

- 是否收到结束打点
- 结束打点是否晚于 `target_window + grace`
- `bytes_read` 是否为 `0`
- `valid_packets` 是否为 `0`

如果 quick QC 直接 reject，你只会看到：

- `Retry take`
- `Quit session`

这类 rejected attempt：

- 不会保存成正式样本
- 不会写入 `takeXX/raw_uart.bin`
- 不会占掉当前 take

如果 quick QC 通过，程序才会展示采集摘要，并让你选择：

- `Accept take`
- `Retry take`
- `Quit session`

## 6. 接受一个 take 之后会发生什么

当你选择 `Accept take` 后，系统会：

- 把本次原始数据保存为 `raw_uart.bin`
- 更新当前 take 的 `status`
- 写入 `accepted_at`
- 写入 `raw_uart_path`
- 写入本次实际 `capture_window`
- 写入本次运行时生成的 `target_window`
- 写入 `marked_window`
- 更新 session 的 `manifest.json`

补充说明：

- `manifest.json` 顶层公共字段和 `config_snapshot` 在 `init-session` 阶段就已经生成
- `Accept take` 这一步主要是在补写当前 take 的产物路径、窗口信息和接受状态
- 如果你想确认这次 session 绑定的是哪份 profile，看 `config_snapshot.config_id`
- 如果你想确认这次 session 实际使用了哪份 mmWave cfg，看顶层 `firmware_config_id`

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
- quick QC 不是频繁因为“没打结束点”被 reject
- 你接受一个 take 后，`raw_uart.bin` 确实生成
- `manifest.json` 被更新
- 下次重新运行 `run-session` 时，会从下一个未完成 take 继续
- 如果后续要把 `raw_uart.bin` 提取成其他产物，应优先读取 manifest 顶层公共字段，不要依赖从 `config_snapshot` 反推

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
3. 等待 `GO`
4. 做动作
5. 在动作结束时按一次 `space`
6. quick QC 通过后，选 `Accept take` 或 `Retry take`

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

### 情况 2：能进入采集，但 quick QC 总是因为空数据 reject

优先检查：

- `data_port` 是否选错
- 雷达是否真的已经启动到输出状态
- 当前 `cfg` 是否和固件兼容

### 情况 3：quick QC 总是因为结束打点失败而 reject

优先检查：

- 是否真的在 `GO` 之后做动作
- 是否在动作结束时按下了 `space`
- 当前终端是不是交互式 TTY
- 是否让动作拖得过长，超过了允许的 `target_window + grace`

### 情况 4：中途退出了，还想继续

直接重新运行：

```bash
uv run vassago collection rd run-session
```

然后重新选择刚才那个未完成 session 即可。

## 10. 对协作者最重要的执行原则

- 先完成 `smoke-test`，再做 collection
- 同一轮 session 尽量保持 `subject_name`、环境和动作配置一致
- 不要猜后台 `capture_window`，只跟着倒计时和 `GO` 操作
- 结束时只按一次结束键，不要沿用旧的双击 `m` 习惯
- `Accept take` 前，先看 quick QC 和摘要是否明显异常
- 不确定时优先 `Retry take`，不要勉强接受明显坏样本
- 中途退出没关系，session 可以恢复
