# RD Collection Profile TOML 说明书

这篇文档是写给“要新建或修改 `configs/collection/rd/profiles/*.toml` 的人”看的。目标只有两个：

- 让你知道每个字段是什么意思
- 让你知道如果不会填，应该去哪里找答案

本文以当前仓库里的真实实现为准，主要对应：

- `configs/collection/rd/templates/rd_template.toml`
- `configs/collection/rd/global.toml`
- `configs/collection/rd/profiles/rd_phase1_default.toml`
- `src/vassago/collection/rd/config.py`

如果旧文档和本文冲突，以本文为准。

## 1. 先建立一个正确心智模型

一份 RD collection profile 不是固件命令文件，也不是采集结果。你可以把它理解成“一张本轮采集意图卡”。

它主要回答 4 个问题：

1. 这份配置叫什么，给谁看
2. 它继承哪份仓库级默认值
3. 它绑定哪份 mmWave `.cfg`
4. 这轮要采什么、默认怎么填、每个动作预计持续多久

它不负责描述的内容包括：

- mmWave 命令本身
- 某次 take 最终生成的 `target_window.start_s / end_s`
- 某台电脑本地临时探测出来的串口状态
- 某次 session 最后实际采到的数据

一句话记忆：

- `profile TOML` 负责“这一轮想怎么采”
- `global.toml` 负责“仓库默认怎么跑”
- `mmwave cfg` 负责“设备实际怎么配置”
- `manifest.json` 负责“这次真的发生了什么”
- 其中 manifest 顶层是 downstream tooling 直接消费的公共 contract
- `config_snapshot` 是一比一复制生效 config 的 provenance snapshot

## 2. 写之前，先准备这 5 个答案

开始写之前，先想清楚：

1. 这份 profile 的稳定名字是什么
2. 它继承哪份 global baseline
3. 它要绑定哪份 mmWave cfg
4. 这轮准备采哪些 gesture / environment
5. 这轮最终想拿到多少个 accepted take，每个 gesture 大概持续多久

如果你不知道这些答案从哪里找，按这个顺序看：

1. 先复制模板：`configs/collection/rd/templates/rd_template.toml`
2. 再看当前 global：`configs/collection/rd/global.toml`
3. 再看目标 cfg 的文件头：`configs/firmware/mmwave/*.cfg`
4. 最后参考现有 profile：`configs/collection/rd/profiles/rd_phase1_default.toml`

大多数时候，你真正需要自己决定的字段只有：

- `config_id`
- `label`
- `description`
- `batch_size`
- `[firmware].default_config_id`
- `[defaults]`
- `[options]`
- `[gesture_target_durations]`

而这些字段通常应该优先沿用模板或 global 默认值：

- `schema_version`
- `capture_window_duration_s`
- `countdown_duration_s`
- `marked_window_end_grace_s`
- `end_mark_key`
- `[serial]`

## 3. 最省心的写法

如果你不是在改运行时机制，而只是要新增一轮采集配置，最稳妥的做法是：

1. 复制 `configs/collection/rd/templates/rd_template.toml`
2. 改文件头元数据
3. 填 `global.config_id`
4. 填 `firmware.default_config_id`
5. 填 `[defaults]`、`[options]`、`[gesture_target_durations]`
6. 除非你非常明确知道为什么要覆盖 global，否则不要加运行时 override

一个典型 profile 会长这样：

```toml
# --- vassago:meta ---
# config_kind = "collection_rd_profile"
# config_id = "rd_phase1_meeting_room"
# label = "RD Phase 1 Meeting Room"
# description = "Meeting-room round for phase-1 swipe/push collection."
# lifecycle = "active"
# ---
schema_version = "collection_rd_profile_v2"
batch_size = 12

[global]
config_id = "rd_global_default"

[firmware]
default_config_id = "rd_pointcloud_dual"

[defaults]
hand = "right"
distance_m = 0.5
angle_deg = 0.0
environment = "meeting_room"
radar_id = "rd_aop_01"
firmware_id = "rd_phase1_uart"

[options]
gestures = ["swipe_left", "swipe_right", "push"]
environments = ["meeting_room", "office_lab"]

[gesture_target_durations]
swipe_left = 1.6
swipe_right = 1.6
push = 1.8
```

## 4. 逐字段解释

### 4.1 文件头元数据

这一段虽然写在注释里，但不是“随手写的说明文字”。仓库会把它当成结构化元数据读取，所以：

- 必须放在文件最开头
- 语法必须和模板一致
- `config_id`、`label`、`description`、`lifecycle` 这类字段只能放这里，不能在正文再写一遍

#### `config_kind`

- 含义：告诉 catalog 这是一份 RD collection profile。
- 怎么填：固定写 `collection_rd_profile`。
- 怎么知道：这是加载器强约束，不是自由字段。

#### `config_id`

- 含义：这份 profile 的稳定主键。代码和其他配置通过它识别 profile，而不是靠文件名。
- 怎么填：用稳定、可读、不容易变的名字。推荐把“域 + 阶段 + 主题”写进去。
- 可参考的命名：`rd_phase1_default`、`rd_phase1_meeting_room`、`rd_phase2_push_only`
- 不要做：不要把 `.toml` 写进 id，不要把磁盘路径当成 id，不要起临时名字。

#### `label`

- 含义：给人看的短标题。
- 怎么填：写成“人一眼能看懂”的名字即可。CLI 列配置时主要展示它。

#### `description`

- 含义：一句话解释这份 profile 是干什么的。
- 怎么填：写“本轮采集用途”，不要只写 `test`、`new config` 这种空话。

#### `lifecycle`

- 含义：标记它是正式可用配置还是模板。
- 怎么填：正式 profile 用 `active`，模板用 `template`。
- 怎么判断：放在 `profiles/` 下准备给人选用的通常就是 `active`；只用于复制起步的模板才是 `template`。

### 4.2 顶层正文字段

#### `schema_version`

- 含义：profile 正文采用的 schema 版本标记。
- 怎么填：直接沿用模板当前值。当前模板里是 `collection_rd_profile_v2`。
- 最重要的原则：不要为了某一份 profile 自己发明一个新字符串。
- 补充：这和 session manifest 里的 `schema_version` 不是同一个东西。

#### `batch_size`

- 含义：这轮 session 计划最终接受多少个 take。
- 怎么填：你希望最后留下多少个 accepted sample，就写多少。
- 例子：希望最终拿到 12 个 accepted take，就写 `12`。
- 容易误解的点：它不是“尝试次数上限”。reject 的 take 不算 accepted，系统会继续直到攒够 accepted take。
- 约束：必须是正整数。
- 当前 manifest 契约：session 初始化时，它会同时写到 manifest 顶层 `batch_size` 和 `config_snapshot.batch_size`。

### 4.3 `[global]`

这一段表示“这份 profile 继承哪份仓库级基线”。

#### `global.config_id`

- 含义：绑定一份 RD global baseline。
- 怎么填：填你要继承的 global 配置 id。
- 去哪里找：看 `configs/collection/rd/global.toml` 的文件头元数据。当前 active global 是 `rd_global_default`。
- 大多数情况下怎么做：如果你没有在做全局基线分叉，直接填 `rd_global_default`。
- 不要做：不要写文件路径，不要把 global 的字段整段复制进 profile 只是为了“看起来完整”。

### 4.4 `[firmware]`

这一段决定“这轮采集前，要向设备发送哪份 repo-managed mmWave cfg”。

#### `firmware.default_config_id`

- 含义：给 session 初始化时的 firmware cfg 方向键列表提供一个默认选中值。
- 怎么填：填你希望默认高亮的 cfg `config_id`。
- 去哪里找：看 `configs/firmware/mmwave/*.cfg` 文件头。当前仓库里能看到的例子包括 `rd_candidate`、`rd_pointcloud_dual` 和 `baseline_pointcloud`。
- 怎么选：如果这轮通常跑点云 + RD 双采集，就把双采集 cfg 设成默认；如果串口链路更脆弱，就把更保守的 cfg 设成默认。
- 不要做：不要写 `config_path`，也不要写磁盘路径。

运行时行为：

- 交互式 `init-session` 会读取当前所有 active mmWave cfg，给操作员一个方向键列表
- `default_config_id` 只决定这个列表默认高亮哪一项
- 本次 session 真正选中的 cfg 会写进 manifest snapshot 里的 `firmware.config_id`

非常重要的区分：

- `[firmware].default_config_id` 是“session 初始化时，firmware cfg 列表默认选哪一项”
- manifest snapshot 里的 `firmware.config_id` 是“这次 session 实际加载了哪份 mmWave cfg”
- `defaults.firmware_id` 是“写进 manifest 的固件/版本标签”

这两个字段不是一回事。

### 4.5 顶层运行时 override

下面这些字段可以直接写在顶层正文里：

- `capture_window_duration_s`
- `countdown_duration_s`
- `marked_window_end_grace_s`
- `end_mark_key`

但如果你没有非常明确的理由，建议不要写，直接继承 global。

#### `capture_window_duration_s`

- 含义：每次 attempt 后台实际录原始 UART 数据的总窗口长度。
- 怎么填：通常沿用 global 默认值。只有你明确要改变整轮采集窗口长度时才覆盖。
- 当前默认：`global.toml` 里是 `5.0`。

#### `countdown_duration_s`

- 含义：从开始到 `GO` 的倒计时长度。
- 怎么填：通常沿用 global 默认值。只有你明确要改变操作员交互节奏时才覆盖。
- 当前默认：`global.toml` 里是 `5.0`。

#### `marked_window_end_grace_s`

- 含义：超过 target 结束点后，系统还能容忍多少额外时间用于结束打点。
- 怎么填：通常沿用 global 默认值。只有你明确要放宽或收紧结束打点容差时才覆盖。
- 当前默认：`global.toml` 里是 `0.25`。

#### `end_mark_key`

- 含义：操作员用于标记动作结束的按键。
- 怎么填：通常沿用 global 默认值。当前默认值是 `space`。

### 4.6 `[serial]`（可选）

这一段用于覆盖串口相关默认值。根据当前加载器，profile 级别支持：

- `cli_port`
- `data_port`
- `cli_baudrate`
- `data_baudrate`

但“支持写”不代表“建议写”。

#### `cli_baudrate` / `data_baudrate`

- 含义：CLI 串口和数据串口的波特率默认值。
- 怎么填：如果设备就是使用 global 默认值，就不要写；只有这轮确实需要不同波特率时才覆盖。
- 当前 global 默认值：`cli_baudrate = 115200`，`data_baudrate = 921600`。

#### `cli_port` / `data_port`

- 含义：给 CLI 交互提供默认串口名。
- 怎么填：共享仓库里的 profile 通常不建议写，因为端口名往往是“某台电脑本地”的，不是 profile 本身的一部分。
- 什么时候可以写：只有在固定实验台、固定设备映射、团队明确接受这种耦合时，才考虑写默认端口。

### 4.7 `[defaults]`

这一段经常被误解。它不是“硬性锁死的真实值”，而是“CLI 创建 session 时给操作员的默认值”。如果操作员改了，最终写进 manifest 的是解析后的实际值。

也就是说，`[defaults]` 更像“表单默认项”，不是“不可更改的真相”。

当前 manifest 契约下：

- `config_snapshot.defaults.*` 保留 profile 的 provenance 默认值
- 操作员最终确认后的实际 session 值，会写到 manifest 顶层对应字段，例如 `hand`、`distance_m`、`angle_deg`、`environment`、`radar_id`、`firmware_id`

#### `defaults.hand`

- 含义：默认手势执行手。
- 怎么填：只能是 `left` 或 `right`，填本轮最常见的那只手。

#### `defaults.distance_m`

- 含义：默认采集距离，单位米。
- 怎么填：如果这轮有明确目标距离，就写那个值；如果只是给操作员一个常用起点，也可以写经验默认值；没有稳定默认值时可以留空不写。

#### `defaults.angle_deg`

- 含义：默认角度，单位度。
- 怎么填：和 `distance_m` 一样，表达的是“默认建议值”；没有明确默认角度时可以留空不写。

#### `defaults.environment`

- 含义：默认环境标签。
- 怎么填：写本轮最常见的环境。
- 重要约束：这个值必须同时出现在 `options.environments` 里。

#### `defaults.radar_id`

- 含义：默认雷达设备标识，最终会写进 manifest。
- 怎么填：写你们团队实际使用的板卡编号、资产编号或实验台编号，例如 `rd_aop_01`、`lab_board_02`。

#### `defaults.firmware_id`

- 含义：默认固件版本标识，最终会写进 manifest。
- 怎么填：写人类可读的固件版本、构建名或阶段名，例如 `rd_phase1_uart`、`fw_20260411_candidate`。
- 再次强调：这里不是 mmWave cfg 的 `config_id`。

### 4.8 `[options]`

这一段描述“这轮允许选什么”。

#### `options.gestures`

- 含义：这轮采集允许的 gesture 清单。
- 怎么填：只列出这轮真的要采的动作。
- 约束：列表必须非空，元素不能重复。
- 当前 manifest 契约：session 初始化时，这组列表会写到 manifest 顶层 `gesture_options`，最终实际选择的 `gesture` 也会单独写到顶层。

从当前 `src/vassago/collection/rd/config.py` 和 `src/vassago/collection/rd/cli.py` 来看，仓库目前没有对 gesture 做中央字典校验。也就是说，技术上它现在是“由 profile 自己定义的一组字符串”。

但实践上建议：

- 优先复用现有命名
- 不要同义乱写
- 已经有 `swipe_left` 时，不要再起一个 `left_swipe`

#### `options.environments`

- 含义：这轮采集允许选择的环境标签清单。
- 怎么填：只列出这轮真的会出现的环境。
- 约束：列表必须非空，元素不能重复，并且必须包含 `defaults.environment`。
- 当前 manifest 契约：session 初始化时，这组列表会写到 manifest 顶层 `environment_options`，最终实际选择的 `environment` 也会单独写到顶层。

从当前实现看，它和 `gestures` 一样，也还没有仓库级中央枚举；但为了后续数据一致性，应该尽量复用已有命名。

### 4.9 `[gesture_target_durations]`

这是 profile 里最容易“看懂字段名，但不知道怎么填”的部分。

先说结论：

- 这里填的不是绝对时间点
- 这里填的是“该 gesture 的理想执行时长”，单位秒

例如：

```toml
[gesture_target_durations]
swipe_left = 1.6
swipe_right = 1.6
push = 1.8
```

它表达的是：

- `swipe_left` 这类动作，理想 target window 时长约为 1.6 秒
- `push` 这类动作，理想 target window 时长约为 1.8 秒

实际的 `target_window.start_s / end_s` 不在 TOML 里写死。系统会在运行时随机生成本次 take 的 target window，再把真实结果写进 manifest。

#### 你应该怎么决定这个数

最实用的判断方法是：

1. 问自己：从 `GO` 到“理想动作完成”，通常要多久
2. 如果已有历史经验，先用以往 good take 的典型时长
3. 如果没有历史数据，先从相近动作的现有 profile 值抄一个起点
4. 左右对称动作通常先保持同样时长，除非你有明确理由区分

不要把这些东西误填进去：

- 倒计时时长
- 总录制时长
- 你希望操作员准备动作的时间

这里只关心“目标动作本身预计持续多久”。

#### 它和 `options.gestures` 的关系

规则很严格：

- `options.gestures` 里出现的每个 gesture，都必须在这里有一个对应项
- 这里不能多写不存在于 `options.gestures` 的 gesture

也就是说，二者必须一一对齐。

#### 它还要满足哪些硬约束

当前加载器会校验：

- 每个值都必须大于 0
- `target_duration + marked_window_end_grace_s` 必须放得进 `capture_window_duration_s`
- `countdown_duration_s` 必须足够长，使运行时能合法随机放置 target window

如果你不想被这些公式困住，可以记一个更实用的经验法则：

- 保持 `capture_window_duration_s = 5.0`
- 保持 `countdown_duration_s = 5.0`
- 把 gesture target duration 放在 1 到 2 秒左右

在当前默认机制下，这通常是安全区间。

## 5. 最容易混淆的几组概念

### 文件名 vs `config_id`

- 文件名只是磁盘上的名字。
- `config_id` 才是仓库管理配置时真正依赖的主键。
- 最好让二者主题一致，但不要把它们当成同一个东西。

### `[firmware].default_config_id` vs `defaults.firmware_id`

- `[firmware].default_config_id` 决定交互式 session 初始化时，默认高亮哪份 mmWave `.cfg`。
- `defaults.firmware_id` 只是 session 初始化时写入 manifest 的默认标签，更像“这轮数据对应的固件版本说明”。

### `global.toml` vs profile 顶层 override

- `global.toml` 是仓库级默认基线。
- profile 顶层 override 是这轮故意偏离全局默认时的局部覆盖。
- 经验建议：能继承就继承，只有这轮真的需要特立独行时才覆盖。

### `[defaults]` vs `[options]`

- `[defaults]` 是交互默认值。
- `[options]` 是可选项全集。
- 例如：`defaults.environment = "office_lab"` 只是默认选中它；`options.environments = ["office_lab", "meeting_room"]` 才表示“这轮允许这两个环境”。

### `gesture_target_durations` vs 实际 `target_window`

- `gesture_target_durations` 是配置里的“时长模板”。
- 实际 `target_window` 是每次运行时真正生成出来的起止窗口，最终写进 manifest。
- 不要在 profile TOML 里写死 `target_window.start_s / end_s`。

### `batch_size` vs 尝试次数

- `batch_size` 是“最后想要多少个 accepted take”。
- 尝试次数可能更多，因为 reject 可能会重试。

## 6. 这份 profile 会怎样进入 manifest

当前实现里，`init-session` 会同时写出两层信息：

- manifest 顶层 public contract：给 downstream tooling 直接消费
- `config_snapshot`：一比一复制生效 config，给 provenance 和 offline QC 对照

最关键的落盘关系如下：

- `batch_size`
  会同时出现在 manifest 顶层 `batch_size` 和 `config_snapshot.batch_size`
- `[defaults]`
  snapshot 保留默认值来源；操作员最终选定的实际 session 值写到 manifest 顶层
- `[options]`
  snapshot 保留来源列表；manifest 顶层额外暴露 `gesture_options`、`environment_options`，以及实际选择的 `gesture`、`environment`
- `[serial]`
  snapshot 保留完整 serial 默认值；如果某个 serial 字段被 downstream tooling 依赖，例如 `data_baudrate`，它也必须稳定出现在 manifest 顶层
- `runtime.*` 与 `gesture_target_durations`
  主要保留在 `config_snapshot`；每次 accepted take 的真实 `capture_window`、`target_window`、`marked_window` 写到 take 顶层

最容易混淆的是三个不同位置的 `schema_version`：

- profile TOML 正文里的 `schema_version`
  表示 profile 文件本身采用的 schema 版本
- manifest 顶层 `schema_version`
  表示 session manifest 的 schema 版本
- `config_snapshot.schema_version`
  表示 snapshot 对象的 schema 版本

它们不是同一个东西，也不应该互相替代。

如果某个字段需要支撑 `raw_uart.bin -> rd.npz` 这类 downstream 路线，而且该路线不应依赖读取 `config_snapshot`，那么这个字段就必须稳定暴露在 manifest 顶层。

## 7. 卡住时，按这个问题判断该去哪填

如果你卡在某个字段，不知道该往哪放，先问自己：

### “这是给机器发现配置用的吗？”

如果是，去看文件头元数据。通常对应：

- `config_kind`
- `config_id`
- `label`
- `description`
- `lifecycle`

### “这是整仓库默认规则，还是只属于这一轮？”

- 如果是整仓库默认规则，去看 `configs/collection/rd/global.toml`
- 如果只是这一轮，写在 profile 自己这里

### “这是设备实际要加载的 cfg 吗？”

如果是：

- 去 `[firmware].default_config_id`
- 去 `configs/firmware/mmwave/*.cfg` 找目标文件的 `config_id`

### “这是 CLI 创建 session 时要给操作员的默认值吗？”

如果是：

- 写到 `[defaults]`

### “这是这轮允许选择的清单吗？”

如果是：

- 写到 `[options]`

### “这是某个动作理想持续多久吗？”

如果是：

- 写到 `[gesture_target_durations]`

## 8. 提交前自检

至少确认这些事：

1. 这份文件是从模板复制出来的，而不是凭记忆手写的
2. 元数据头在文件最开头，语法和模板一致
3. `config_kind = "collection_rd_profile"`
4. `config_id` 稳定、可读、唯一
5. `lifecycle` 与文件角色一致
6. `global.config_id` 指向存在的 global 配置
7. `firmware.default_config_id` 指向存在的 mmWave cfg
8. `defaults.environment` 出现在 `options.environments` 里
9. `options.gestures` 与 `gesture_target_durations` 完整对齐
10. 如果没有明确理由，没有额外覆盖 global 的运行时字段

如果你想做机器校验，可以运行：

```bash
uv run python -m vassago.configs.validation
```

如果你想确认 active profile 是否能被 CLI 正常列出来，可以运行：

```bash
uv run vassago collection rd list-configs
```

## 9. 最后给一个最实用的原则

新增 profile 时，优先做“最小改动”。

也就是：

- 复制模板
- 改元数据头
- 选对 global
- 选对 firmware cfg
- 填本轮真正不同的 defaults / options / durations

除此之外，先不要主动发明新字段，也不要急着覆盖全局运行时参数。

如果你能用“只改这一轮真正不同的部分”完成目标，这份 profile 大概率就是健康的。
