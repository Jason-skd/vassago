# Live Visualizer TLV Parse Regression

## Meta

- Date: 2026-04-14
- Scope: capture
- Status: active
- Requested By: user
- Authors:
  - Codex
- Related Branch:
  - `main`
- Related Commits:
  - pending
- Related Files:
  - `src/vassago/firmware/mmwave/protocol.py`
  - `src/vassago/firmware/mmwave/point_cloud.py`
  - `src/vassago/collection/rd/visualizer.py`
  - `tests/test_mmwave_protocol.py`
  - `configs/collection/rd/profiles/rd_phase1_default.toml`
  - `configs/firmware/mmwave/rd_pointcloud_dual.cfg`

## Background

在 2026-04-13 晚上的 live capture 使用中，operator 观察到 point-cloud visualizer
只有在手非常靠近雷达时才会稳定显示，稍远一些基本不出点。

第一眼看起来像是：

- `rd_pointcloud_dual.cfg` 的 CFAR / FOV 设置过于激进
- visualizer 的视角或坐标映射有问题
- 双输出模式把 UART 压得过紧，导致远距离帧更容易掉

但离线检查当晚 session 的 `raw_uart.bin` 之后，发现更核心的问题在 packet/TLV
解析层，而不是 GUI 绘制层。

## Decision / Findings

已确认结论如下：

1. 默认 RD collection profile 当前绑定的是 `rd_pointcloud_dual`，不是保守的
   `baseline_pointcloud`。
2. live capture 的 visualizer 不直接啃原始串口，而是消费
   `MmwavePacketParser` 产出的 packet。
3. `MmwavePacketParser` 先前的 best-effort 路径选择规则过于粗糙：
   - 主要只看“解析出多少个 TLV”
   - TLV 数相同后，只看 `offset` 是否更靠后
   - 一旦先遇到某条“TLV 数已经等于 header 里 `num_tlvs`”的路径，就提前退出
4. 在 `rd_pointcloud_dual` 产生的真实 packet 里，TLV `length` 既可能被解释成
   total length，也可能被解释成 payload length。
   某些 payload-mode packet 加上尾部 padding 后，会同时存在多条“TLV 数量同样正确”
   的候选路径。
5. 旧 heuristic 会把更靠后的错误路径排在正确路径前面。典型症状是：
   - `tlv_type` 被读成很大的垃圾整数
   - `type=1` 点云 TLV payload 长度被误读成 `8` 或 `24`
   - `extract_point_cloud_frame()` 因 payload 不是 `16B * N` 而抛 `ValueError`
   - visualizer 在 `consume_packets()` 中吞掉这个 `ValueError`，于是整帧静默丢失
6. “手要很近才有显示”的表象来自二次效应：
   - 近距离回波更强，帧里点更多
   - 某些帧即使存在 TLV 解析歧义，也更容易碰巧走到正确路径
   - sparse frame 则更容易被误解析后直接丢掉

本轮修复不引入 config 级 `tlv_length_mode` 开关，而是先把 protocol parser 的
路径评分改为：

- 先看 TLV 数量
- 再看 trailing padding 是否小且按 32-bit 对齐
- 再看 payload 长度是否更像正常 TLV
- 再看 `tlv_type` 是否更像合理的小整数
- 再看是否减少重复 TLV type
- 最后才用 `offset` 做平局打破

同时移除了“先碰到任意满 `num_tlvs` 路径就提前退出”的行为。

## Alternatives Considered

### 1. 直接给 `rd_pointcloud_dual` 增加显式 `tlv_length_mode = "payload"`

没有在本轮采用。

原因：

- 当前受管 mmWave cfg 有 integrity 约束，不应随手改已有 cfg 内容
- 这次问题不是“当前 cfg 真的需要特殊私货”，而是 parser 对歧义路径打分太弱
- 如果 parser 层能更稳地选出合理路径，live capture、smoke-test、offline replay
  都会一起受益

### 2. 在 visualizer 层做容错，遇到异常时尝试另一种点云格式

没有在本轮采用。

原因：

- 问题根源在 packet/TLV 边界恢复，而不是 GUI
- 如果上游 packet 已经错位，visualizer 层猜格式只会继续放大混乱
- 正确边界应该统一在 `protocol.py`

### 3. 为当前修复直接依赖 2026-04-13 的实采 packet 做测试

没有在本轮采用。

原因：

- 回归测试应尽量自包含，不依赖 `data/` 目录里的实采样本
- 可以用一个更小的 synthetic packet 稳定复刻同类歧义

## Consequences

这次修复的直接影响：

- live capture visualizer 会更稳定地收到可解码的点云 TLV
- 当前 `rd_pointcloud_dual` 路径下，“近了才显示”的假象会明显缓解
- smoke-test / summary / offline replay 复用同一 parser 时，也会一起受益

这次修复没有声称解决的事：

- `rd_pointcloud_dual` 的检测灵敏度、FOV 和 UART 压力本身仍然会影响可见点数
- 若后续接入另一类固件，真的同时存在多种合法 TLV 语义格式，未来仍可能需要
  config 级的 `tlv_length_mode` 或更显式的协议 profile

## Next Actions

1. 用当前 parser 修复后的 live capture 再跑一次 `rd_pointcloud_dual` 实机验证。
2. 对 2026-04-13 的 session 再做离线复核，确认可解码点云帧数量显著提升。
3. 如果后续又发现另一类固件在 parser 层存在真实冲突，再讨论是否引入 config
   级 `tlv_length_mode`。

## Verification / Open Questions

已验证：

- 默认 profile 绑定 `rd_pointcloud_dual`
- live visualizer 依赖共享 `MmwavePacketParser`
- 旧 heuristic 会在 synthetic ambiguity packet 上选错路径
- 旧 heuristic 也会在 2026-04-13 的真实 session packet 上把部分 `type=1` TLV
  误解析成 `8B` 或 `24B` payload
- 对同一批 2026-04-13 session 离线复核后，可解码点云帧数量已从
  `27/31/38/38` 提升到 `53/52/53/52`
- 剩余 2 个异常 packet 更像是原始串口数据本身不完整或局部损坏，而不是同一类
  TLV 路径评分问题

本轮代码修复后需要继续确认：

- 实机 live capture 下 visualizer 的主观可见性是否已经恢复到可用水平
- 是否还有别的 TLV 组合会触发类似的“同 TLV 数但更差路径”问题

当前仍保留的开放问题：

- 是否最终仍需要 config 级 `tlv_length_mode`，以覆盖未来不同固件族的协议差异
