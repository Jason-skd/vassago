# 毫米波雷达第一阶段实践：先采 RD 数据

## 文档定位

这不是完整技术方案，而是 `Phase 1` 的范围收敛文和最小样本契约。

它服务于一个非常明确的目标：

- 尽快形成第一版可用的手势 `RD` 数据集
- 当前只依赖板子的 `Type-C -> UART` 链路
- 当前不要求先实现近似 `uD` 计算脚本
- 当前不追求 `LVDS/raw ADC`、真正的 `micro-Doppler`、`RA`、点云和完整训练流水线

一句话：

`Phase 1` 只做一件事：稳定采到可复用、可重算、可质检的 `RD` 序列。

## 为什么这一版先只做 RD

对当前“尽快拿到第一版手势数据集”的需求，`RD` 是最划算的主数据类型：

- `RD` 直接描述“距离-速度”分布，已经覆盖手势最重要的动态信息
- 后续的近似 `uD` 可以从 `RD` 序列离线推导，不必现在同步完成
- `UART` 链路更有可能承载单一 `RD` 输出，而不是同时承载 `RD + RA + 点云`
- 相比先做 3D 或点云，`RD` 更接近你当前真正要解决的“动作识别”问题

因此，第一阶段只保留一条主链路：

`raw_uart.bin -> rd.npz -> 近似 uD`

## 第一阶段不做什么

- 不做 `raw ADC / LVDS` 采集
- 不做真正意义上的 `micro-Doppler`
- 不要求同时采 `RA`
- 不要求点云
- 不要求第一版就完成完整训练流水线
- 不做多模态同步采集

## 为什么第一阶段仍然保留 `raw_uart.bin`

当前通过 `Type-C` 采到的不是 `raw ADC`，而是数据串口输出的原始 `UART/TLV` 二进制流。

这个 `bin` 仍然必须保留，因为它有直接工程价值：

- 以后解析器改了，可以重解析，不必重新采样
- 如果后续打开了新的 TLV 类型，可以回放旧数据验证解析逻辑
- 可以区分“采集问题”和“解析问题”
- 可以作为 `RD` 的上游原始证据
- 可以支撑后续质量回查和故障定位

因此，第一阶段单条样本的最小产物不是只有一个 `.npy`，而是：

- `meta.json`
- `raw_uart.bin`
- `rd.npz`

## 数据最小契约

### 样本目录

建议每条样本一个目录：

```text
data/
  rd_samples/
    swipe_left_20260407_203015_p01_take01/
      meta.json
      raw_uart.bin
      rd.npz
```

命名建议：

`{gesture}_{YYYYMMDD_HHMMSS}_{subject_id}_{take_id}`

例如：

`swipe_left_20260407_203015_p01_take01`

### `meta.json`

`meta.json` 是这条样本的业务标签和工程元信息。第一阶段至少必须包含以下字段。

#### 必填业务字段

- `sample_id`: 字符串，样本唯一 ID
- `gesture`: 字符串，手势标签
- `subject_id`: 字符串，被试编号
- `hand`: 字符串，`left` 或 `right`
- `distance_m`: 数值，采集距离，单位米
- `angle_deg`: 数值，人体相对雷达中心方向，单位度
- `speed`: 字符串，`slow`、`normal`、`fast`
- `environment`: 字符串，环境编号，如 `office_a`
- `session_id`: 字符串，同一轮采集会话编号

#### 必填工程字段

- `radar_id`: 字符串，设备编号
- `firmware_id`: 字符串，固件或 demo 标识
- `parser_version`: 字符串，解析器版本号
- `config_id`: 字符串，配置版本标识，例如 `rd_v1`
- `config_path`: 字符串，仓库内配置文件路径
- `config_sha256`: 字符串，配置文件哈希
- `cli_port`: 字符串，CLI 串口名
- `data_port`: 字符串，Data 串口名
- `data_baudrate`: 整数，例如 `921600`
- `capture_duration_s`: 数值，本次采集总时长，单位秒
- `expected_frame_period_s`: 数值，来自配置的目标帧周期，单位秒
- `expected_frame_count`: 整数，理论目标帧数
- `parsed_frame_count`: 整数，成功解析出的 `RD` 帧数
- `frame_gap_count`: 整数，依据 `frame_id` 检测到的缺失帧数
- `parse_success_rate`: 数值，`parsed_frame_count / expected_frame_count`
- `start_time`: 字符串，ISO 8601 开始时间
- `end_time`: 字符串，ISO 8601 结束时间

#### 推荐补充字段

- `notes`: 字符串，异常情况备注
- `operator_id`: 字符串，采集者编号
- `mount_id`: 字符串，雷达安装方式编号
- `room_id`: 字符串，房间编号
- `warmup_discard_frames`: 整数，预热丢弃帧数

#### `meta.json` 最小示例

```json
{
  "sample_id": "swipe_left_20260407_203015_p01_take01",
  "gesture": "swipe_left",
  "subject_id": "p01",
  "hand": "right",
  "distance_m": 0.5,
  "angle_deg": 0.0,
  "speed": "normal",
  "environment": "office_a",
  "session_id": "20260407_night_a",
  "radar_id": "sr112_01",
  "firmware_id": "oob_rd_uart_v1",
  "parser_version": "rd_parser_v1",
  "config_id": "rd_v1",
  "config_path": "configs/rd_v1.cfg",
  "config_sha256": "7f4c2f0f...",
  "cli_port": "/dev/cu.usbmodem1103",
  "data_port": "/dev/cu.usbmodem1101",
  "data_baudrate": 921600,
  "capture_duration_s": 2.5,
  "expected_frame_period_s": 0.033,
  "expected_frame_count": 75,
  "parsed_frame_count": 71,
  "frame_gap_count": 2,
  "parse_success_rate": 0.9467,
  "start_time": "2026-04-07T20:30:15.231+08:00",
  "end_time": "2026-04-07T20:30:17.812+08:00",
  "warmup_discard_frames": 5,
  "notes": ""
}
```

### `raw_uart.bin`

`raw_uart.bin` 保存采集窗口内从 Data 串口读到的原始字节流。

约束：

- 不做额外解码
- 不做文本转换
- 不做按帧拆分
- 保留采集开始到结束之间收到的全部原始字节

它不是 `raw ADC`，而是当前 demo 通过 `UART` 发出的原始包。

### `rd.npz`

`rd.npz` 保存解析后的 `RD` 数值结果。第一阶段必须把定义说死，避免后续歧义。

#### 核心约定

- `rd` 的形状固定为 `[T, R, D]`
- `T` 表示时间帧数
- `R` 表示距离 bin 数
- `D` 表示 Doppler bin 数
- `rd` 的 `dtype` 固定为 `float32`
- `rd` 的语义固定为“每帧 `Range-Doppler` 功率图的线性功率值”
- `rd` 中所有元素必须是有限值，不允许 `NaN` 或 `Inf`
- `rd` 中所有元素必须非负

第一阶段不把 `rd` 存成：

- 复数频谱
- dB 值
- 为可视化拉伸后的 8-bit 图像

原因：

- 复数形式在当前 UART 路线下不现实
- dB 和 8-bit 图像会丢失后续近似 `uD` 所需的幅度关系
- 线性功率 `float32` 最稳，后续要做对数压缩或归一化都来得及

#### 必填数组

- `rd`: `float32[T, R, D]`
- `frame_ids`: `uint32[T]`
- `frame_times_host_s`: `float64[T]`
- `range_bin_m`: `float32[R]`
- `doppler_bin_mps`: `float32[D]`

#### 可选数组

- `valid_mask`: `bool[T]`
- `frame_packet_sizes`: `uint32[T]`

#### 时间定义

`frame_times_host_s` 定义为：

- 主机侧时间
- 以样本开始采集时刻为 `0.0`
- 每一帧在主机上完成接收并成功解析时记录的相对秒数

第一阶段不依赖设备内时间戳，因为 UART demo 未必稳定提供可用设备时间。

#### bin 轴定义

`range_bin_m` 定义为每个距离 bin 中心对应的物理距离，单位米。  
`doppler_bin_mps` 定义为每个 Doppler bin 中心对应的物理速度，单位米每秒。

要求：

- `range_bin_m` 单调递增
- `doppler_bin_mps` 必须是带符号速度轴
- 零 Doppler 必须在数组中间附近
- 如果原始输出未居中，解析后必须执行等价于 `fftshift` 的重排，确保 `doppler_bin_mps` 从负到正有序排列

#### `rd.npz` 最小示例

```python
{
    "rd": float32[T, R, D],
    "frame_ids": uint32[T],
    "frame_times_host_s": float64[T],
    "range_bin_m": float32[R],
    "doppler_bin_mps": float32[D],
}
```

## 配置版本机制

第一阶段不强制每条样本复制一份 `.cfg` 文件，只记录 `config_id` 即可。

但这个假设只在以下机制成立时有效：

- `config_id` 对应一个仓库内固定文件
- 例如 `config_id = rd_v1` 必须唯一对应 `configs/rd_v1.cfg`
- `meta.json` 中必须同时记录 `config_path`
- `meta.json` 中必须同时记录 `config_sha256`
- 修改配置内容时必须创建新的 `config_id`

禁止做法：

- 沿用旧 `config_id`，但偷偷改配置内容
- 不记录配置文件路径
- 不记录配置文件哈希

对第一阶段来说，`config_id + config_path + config_sha256` 就足够建立可追溯性。

## 面向当前需求的采样优先级

你的当前目标不是做最完整的数据集，而是尽快拿到“最有效的第一版手势数据”。因此采样优先级应该这样排：

1. 先保证 `RD` 序列稳定可用
2. 再保证被试多样性
3. 再保证每类样本数量
4. 再引入距离和速度变化
5. 最后才是角度、环境和更复杂条件

换句话说，时间紧的时候，优先级不是“先把维度采全”，而是“先把主模态采稳”。

## 第一阶段建议采样设计

### 手势类别

建议第一轮只做：

- `8` 到 `10` 个手势类别
- `2` 个负样本类别

负样本建议固定包含：

- `idle`: 人在场但不做目标动作
- `random_motion`: 非目标乱动

### 样本时长

单条样本建议固定为 `2.5s`：

- 前静止 `0.5s`
- 动作执行 `1.5s`
- 后静止 `0.5s`

如果现场执行困难，最低可接受 `2.0s`，但不建议更短。

### 被试和次数

第一版最低建议：

- 被试人数：`10`
- 每类每人次数：`20`

如果资源允许，更稳妥的是：

- 被试人数：`15` 到 `20`
- 每类每人次数：`20` 到 `30`

### 距离、角度、速度

第一阶段为了让数据“既有效又不失控”，建议用分层策略：

#### 第一优先层

- 距离：`0.5m`
- 角度：`0°`
- 速度：`normal`

先用这组条件把主数据量做出来。

#### 第二优先层

- 距离：`0.3m`、`0.8m`
- 速度：`slow`、`fast`

#### 第三优先层

- 角度：`-20°`、`+20°`
- 第二环境：例如另一个办公室

如果采集时间不够，宁可暂时不加角度和环境，也不要牺牲被试人数和每类样本数。

## 采样 SOP

### 每日开始前

每天采集开始前，固定执行：

1. 设备上电并等待稳定
2. 下发配置并启动采集程序
3. 丢弃预热帧，建议 `5` 到 `10` 帧
4. 录制 `30s` 空场景
5. 录制 `10s` 人在场但静止

这两段基线数据不一定进入主训练集，但必须保留，用于排查噪声和环境变化。

### 单条样本流程

单条样本的执行流程建议固定：

1. 操作者输入标签和元信息
2. 开始采集
3. 前静止 `0.5s`
4. 执行一个完整动作
5. 后静止 `0.5s`
6. 停止采集
7. 保存 `meta.json + raw_uart.bin + rd.npz`
8. 立即做自动验收

约束：

- 一条样本只允许一个动作实例
- 不允许一条样本里连续做多个不同动作
- 采集期间雷达和底座保持不动
- 采集期间不要改配置

### 会话内原则

- 同一 `session_id` 内尽量保持同一配置
- 同一批数据尽量使用同一安装方式和朝向
- 配置一旦更改，必须切换 `config_id`
- 当天出现明显异常时，在 `notes` 中记录

## 自动验收标准

第一阶段每条样本至少满足以下门槛，否则标记为不合格或待复采：

### 基础结构

- `meta.json` 存在且可解析
- `raw_uart.bin` 存在且非空
- `rd.npz` 存在且可加载

### `rd.npz` 结构正确

- `rd.ndim == 3`
- `rd.shape == [T, R, D]`
- `T >= 1`
- `R >= 1`
- `D >= 1`
- `frame_ids.shape == [T]`
- `frame_times_host_s.shape == [T]`
- `range_bin_m.shape == [R]`
- `doppler_bin_mps.shape == [D]`

### 数值有效

- `rd.dtype == float32`
- `rd` 中无 `NaN`
- `rd` 中无 `Inf`
- `rd` 中所有值 `>= 0`
- `frame_times_host_s` 严格递增
- `range_bin_m` 单调递增
- `doppler_bin_mps` 单调递增

### 帧质量

定义：

- `expected_frame_count = round(capture_duration_s / expected_frame_period_s)`
- `parse_success_rate = parsed_frame_count / expected_frame_count`

门槛建议：

- `parsed_frame_count >= max(45, 0.8 * expected_frame_count)`
- `parse_success_rate >= 0.8`
- `frame_gap_count <= 0.1 * expected_frame_count`

这些门槛偏务实，适合第一阶段先保住数据量；后续可以再提高。

### 可回放性

至少应满足：

- 能从 `raw_uart.bin` 稳定重解析出与 `rd.npz` 相同数量级的 `RD` 帧
- 重解析后的 `R`、`D` 维度与存盘结果一致

## 数据最有效的取舍原则

为了让第一版数据尽快可用，采集取舍遵循以下原则：

- 宁可先只采 `RD`，也不要为了多模态把主链路搞不稳定
- 宁可先不算近似 `uD`，也要先把 `RD` 和 `raw_uart.bin` 留住
- 宁可少一些环境变化，也要先保证被试人数和样本数
- 宁可固定一版配置，也不要中途频繁改参数
- 宁可保留原始串口包多占一点磁盘，也不要让数据失去重算能力

## 当前版本的实践定义

第一阶段的实践定义如下：

- 目标：尽快形成第一版 `RD` 数据集
- 主数据：`RD`
- 派生数据：后续再从 `RD` 推近似 `uD`
- 样本最小文件：`meta.json + raw_uart.bin + rd.npz`
- 配置追踪方式：`config_id + config_path + config_sha256`
- 样本主结构：每条样本一个目录
- 单条样本时长：优先 `2.5s`
- 优先采样策略：先被试和样本量，再条件多样性

## 备注

如果未来需要更高质量的 `micro-Doppler`，仍然应转向 `LVDS + raw ADC` 采集链路。当前 `Phase 1` 方案只服务于尽快落地 `RD` 数据集，并为后续近似 `uD` 留足重算空间。
