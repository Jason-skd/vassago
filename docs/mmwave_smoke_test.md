# mmWave Firmware Smoke Test 工具说明书

## 1. 工具定位

`mmwave_smoke_test` 是一个最小联调工具，用于验证毫米波雷达开发板在当前固件下是否具备基本可用性。

本工具只回答以下问题：

1. 主机是否识别到板子的双串口
2. `CLI` 串口是否可用
3. 固件是否能够成功启动
4. `Data` 串口是否持续输出合法 UART 二进制包

本工具不负责：

- `RD` 数组重建
- `raw_uart.bin -> rd.npz` 数据采集闭环
- 手势识别
- 模型训练

因此，它是联调检查工具，不是正式采集程序。

## 2. 适用场景

建议在以下场景使用本工具：

- 板子刚完成固件烧录
- 设备刚切回运行模式
- 串口号发生变化，需要重新识别 `CLI` / `Data` 口
- 需要判断当前问题出在固件启动、串口链路还是上位机解析

## 3. 相关文件

- 脚本入口：`src/vassago/mmwave_smoke_test.py`
- 保守点云配置：`configs/oob_pointcloud_safe.cfg`
- TI `xWR68xx_AOP` 基线配置：`configs/oob_pointcloud_ti_xwr68xx_aop.cfg`
- 常规点云烟雾配置：`configs/oob_pointcloud_smoke.cfg`
- `RD` 候选配置：`configs/rd_phase1_candidate.cfg`

## 4. 环境前提

执行测试前，应满足以下条件：

- 开发板已正确接线并上电
- 固件已完成烧录
- 板子已切回正常运行模式，而非烧录模式
- 本地 Python 环境和项目依赖已安装完成

在板型未知时，必须先确认频段和固件路线：

- `60GHz / xWR68xx_AOP / out_of_box_6843_aop.bin`
- `77GHz / xWR18xx_AOP / out_of_box_1843_aop.bin`

板型、固件、配置文件必须匹配。  
当三者不匹配时，常见现象为：

- `CLI` 串口可打开，但 `sensorStart` 失败
- `Data` 串口始终无数据

## 5. 串口模型

设备通常暴露两个串口：

- `CLI` 串口：命令通道，用于下发 `.cfg`
- `Data` 串口：数据通道，用于接收雷达输出

在 macOS 上，串口名可能随设备重新枚举而改变，例如：

- `/dev/cu.SLAB_USBtoUART`
- `/dev/cu.SLAB_USBtoUART5`
- `/dev/cu.SLAB_USBtoUART6`

这是正常现象，不代表设备异常。  
每次重新插拔设备、切换模式或重新烧录后，都应重新执行一次串口枚举。

## 6. 命令行接口

### 6.1 枚举串口

```bash
uv run python -m vassago.mmwave_smoke_test --list-ports
```

用途：

- 列出当前主机可见的串口设备
- 用于定位板子的两个 `SLAB` 串口

典型输出：

```text
/dev/cu.SLAB_USBtoUART - CP2105 Dual USB to UART Bridge Controller
/dev/cu.SLAB_USBtoUART6 - CP2105 Dual USB to UART Bridge Controller
```

### 6.2 执行烟雾测试

```bash
uv run python -m vassago.mmwave_smoke_test \
  --cli-port /dev/cu.SLAB_USBtoUART \
  --config configs/oob_pointcloud_safe.cfg \
  --data-port /dev/cu.SLAB_USBtoUART6 \
  --duration 5 \
  --verbose
```

用途：

- 通过 `CLI` 串口下发配置
- 通过 `Data` 串口接收数据
- 输出最小可用性判断结果

### 6.3 主要参数

- `--list-ports`
  只列出串口并退出。

- `--cli-port`
  指定命令串口路径。

- `--data-port`
  指定数据串口路径。

- `--config`
  指定要下发的 `.cfg` 文件路径。

- `--cli-baudrate`
  指定 `CLI` 串口波特率，默认 `115200`。

- `--data-baudrate`
  指定 `Data` 串口波特率，默认 `921600`。

- `--duration`
  指定数据口监听时长，单位秒，默认 `5`。

- `--min-packets`
  指定通过所需的最少合法包数量，默认 `3`。

- `--verbose`
  打印更详细的逐帧输出。

## 7. 标准操作流程

建议按以下顺序执行。

### 7.1 串口枚举

先执行：

```bash
uv run python -m vassago.mmwave_smoke_test --list-ports
```

若未看到两个 `SLAB` 串口，应先排查：

- USB 线是否正常
- 设备是否上电
- 主机驱动是否正常

### 7.2 第一轮测试

第一轮测试优先使用保守点云配置：

```bash
uv run python -m vassago.mmwave_smoke_test \
  --cli-port /dev/cu.SLAB_USBtoUART \
  --config configs/oob_pointcloud_safe.cfg \
  --data-port /dev/cu.SLAB_USBtoUART6 \
  --duration 5 \
  --verbose
```

如果失败，再交换 `CLI` / `Data` 口重试一次。

### 7.3 第二轮测试

若保守配置在 `sensorStart` 阶段失败，则建议使用 TI `xWR68xx_AOP` 基线配置：

```bash
uv run python -m vassago.mmwave_smoke_test \
  --cli-port /dev/cu.SLAB_USBtoUART \
  --config configs/oob_pointcloud_ti_xwr68xx_aop.cfg \
  --data-port /dev/cu.SLAB_USBtoUART6 \
  --duration 5 \
  --verbose
```

该配置适用于验证 `60GHz / xWR68xx_AOP / out_of_box` 路线。

### 7.4 后续测试顺序

推荐的整体配置尝试顺序如下：

1. `configs/oob_pointcloud_safe.cfg`
2. `configs/oob_pointcloud_ti_xwr68xx_aop.cfg`
3. `configs/oob_pointcloud_smoke.cfg`
4. `configs/rd_phase1_candidate.cfg`

说明：

- 第 1 份配置优先验证“设备能否稳定启动”
- 第 2 份配置优先验证“TI 标准 `xWR68xx_AOP` 路线是否成立”
- 第 3 份配置用于验证常规点云输出路径
- 第 4 份配置仅用于在串口链路已稳定后尝试 `RD` 输出

若前两份配置均无法通过 `sensorStart`，不建议继续尝试 `RD` 配置，应优先回到固件和板型匹配检查。

## 8. 输出结果说明

### 8.1 成功输出

通过时通常可见如下结构：

```text
Smoke test summary
  bytes_read: 123456
  valid_packets: 20
  invalid_packets: 0
  first_frame: 101
  last_frame: 120
  frame_gaps: 0
  non_monotonic_frames: 0
  tlv_types: {1: 20}
  result: PASS
```

关键判断条件：

- `bytes_read > 0`
- `valid_packets > 0`
- `result: PASS`

只要满足这三项，即可认为：

- 固件已成功启动
- `Data` 串口正在输出结构化数据
- 上位机已能识别当前 UART 包格式

### 8.2 `CLI did not become ready before config`

含义：

- 已打开目标串口
- 但脚本未收到设备返回的 `mmwDemo:/>` 提示符

优先排查：

- 设备是否刚重启，应用尚未完成启动
- 当前是否仍处于烧录模式
- 当前固件是否不是 `mmwDemo / out_of_box` 路线
- 串口是否因重新枚举而发生变化

处理建议：

1. 重新插拔设备
2. 重新执行 `--list-ports`
3. 重新识别 `CLI` 串口
4. 必要时重烧正确固件

### 8.3 `Config timed out before data capture`

含义：

- 某条配置命令已经发送
- 但设备在预期时间内未返回响应

辅助信息：

```text
stalled_command: ...
```

表示发生超时的具体命令。

优先排查：

- 串口是否选错
- 固件是否不兼容当前配置
- 设备是否在执行过程中卡死

### 8.4 `Config failed before data capture`

含义：

- 固件已明确返回异常或错误

最常见形式为：

```text
failed_command: sensorStart
```

这通常表示：

- 板型与配置不匹配
- 固件与配置不匹配
- 配置参数组合超出当前固件支持范围

### 8.5 `bytes_read: 0` 且 `valid_packets: 0`

含义：

- `CLI` 配置阶段看似成功
- `Data` 串口没有任何有效输出

优先排查：

- `Data` 串口是否选错
- 当前固件是否真的输出 UART 数据
- `guiMonitor` 是否启用了任何输出项

## 9. 配置文件说明

### 9.1 `configs/oob_pointcloud_safe.cfg`

用途：

- 提供最保守的点云启动配置
- 优先确认设备和串口链路是否基本正常

适用时机：

- 刚完成烧录
- 设备状态不稳定
- 需要最小化参数复杂度

### 9.2 `configs/oob_pointcloud_ti_xwr68xx_aop.cfg`

用途：

- 提供基于 TI `xWR68xx_AOP` 示例的基线配置
- 用于验证 `60GHz / out_of_box` 路线

适用时机：

- 保守配置在 `sensorStart` 失败
- 需要排除“自定义 cfg 写错”这一因素

### 9.3 `configs/oob_pointcloud_smoke.cfg`

用途：

- 提供常规点云输出路径的烟雾测试配置

适用时机：

- 基础链路已打通
- 需要验证与同类项目更接近的点云输出行为

### 9.4 `configs/rd_phase1_candidate.cfg`

用途：

- 用于尝试面向 `Phase 1` 的 `RD` 输出路径

适用时机：

- 固件已确认可以稳定启动
- `CLI` 和 `Data` 串口均已确认
- 点云链路已验证通过

## 10. 对烧录同事的要求

如需由同事重新烧录固件，至少应确认以下事项：

1. 板子频段是 `60GHz` 还是 `77GHz`
2. 烧录的 bin 与板型是否匹配
3. 烧录完成后是否已切回正常运行模式
4. 上电后在串口终端按回车，是否能看到 `mmwDemo:/>`

若第 4 项无法满足，则当前问题不应继续归因于上位机脚本。

## 11. 判定结论

当输出满足以下条件时，可判定最小联调通过：

- `CLI` 提示符可见
- 配置文件可成功下发
- `sensorStart` 成功
- `Data` 串口读到合法包
- 最终结果为 `PASS`

若连 `CLI` 提示符都无法稳定出现，应优先排查：

- 固件是否正确
- 板子是否处于运行模式
- 板型与固件是否匹配

在这些问题未确认前，不建议继续推进 `RD` 采集或算法分析。
