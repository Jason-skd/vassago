# `configs/` 目录指南

这篇文档固定说明仓库里 `configs/` 的目录结构、文件放置规则和编辑边界。

如果你要新增、移动、重命名或删除 repo-managed 配置，先看这里；如果你要执行发现、校验或验收命令，再看 [configs-command-guide.md](configs-command-guide.md)。

## 1. 先记一个总原则

`configs/` 是当前仓库唯一的 repo-managed config home。

也就是说：

- 进入版本管理、需要被 CLI 或 loader 发现的正式配置，都应放在 `configs/` 下
- 根目录不要再散落某个业务域自己的 `.toml` 或 `.cfg`
- 目录划分优先按“业务域”，再按“文件角色”

一句话记忆：

- 先看这个配置属于 `firmware`、`collection` 还是 `registry`
- 再决定它是 `global`、`profile`、`companion`、`template` 还是治理资源

## 2. 当前真实目录树

当前仓库里和配置相关的正式目录如下：

```text
configs/
  registry/
    catalog_roots.toml
    mmwave_cfg_commands.toml
    mmwave_cfg_integrity.toml

  firmware/
    mmwave/
      baseline_pointcloud.cfg
      rd_candidate.cfg
      rd_pointcloud_dual.cfg

  collection/
    rd/
      global.toml
      companions/
        rd_background_default.toml
      profiles/
        rd_phase1_default.toml
      templates/
        rd_template.toml
```

如果你准备新增新域，先确认它是不是已经稳定到值得进入这棵树；不要因为一次性实验就把目录树越分越碎。

## 3. 各目录边界

### `configs/registry/`

这里放“治理配置”，不是业务采集结果，也不是运行期临时状态。

当前包括：

- `catalog_roots.toml`
  定义 repo-managed config discovery roots
- `mmwave_cfg_commands.toml`
  定义 mmWave cfg 命令表与语义校验依据
- `mmwave_cfg_integrity.toml`
  记录受管 mmWave cfg 的完整性摘要

适合放在这里的内容：

- discovery 规则
- schema policy
- 校验注册表
- 其他全仓共享的配置治理资源

不适合放在这里的内容：

- 某一轮采集 profile
- 某一块板子的 `.cfg`
- 本机临时串口覆盖

### `configs/firmware/mmwave/`

这里放仓库正式管理的 TI-style mmWave `.cfg`。

这些文件会被多个入口复用：

- `vassago firmware mmwave smoke-test`
- `vassago collection rd init-session`
- `vassago processing rd extract`

放在这里的前提通常是：

- 这份 cfg 需要长期保留
- 它应该能被 `config_id` 稳定引用
- 它值得进入 catalog、校验和 integrity registry

放置规则：

- 文件头必须带完整 metadata header
- `config_id` 才是主键，文件名只是 locator
- 已存在 cfg 内容发生实质变化时，优先判断是否应该新建 `config_id`

### `configs/collection/rd/global.toml`

这里放 RD collection 的仓库级默认运行时基线。

当前它承载的是整仓共享的稳定默认值，例如：

- `capture_window_duration_s`
- `countdown_duration_s`
- `marked_window_end_grace_s`
- `end_mark_key`
- 默认串口波特率

适合放进 `global.toml` 的内容：

- 对整个 RD collection 域都成立的稳定 runtime 基线
- 不属于某一轮特定采集的默认策略

不适合放进去的内容：

- 某一轮专属动作列表
- 某一轮默认环境或手别
- 某一台机器的本地串口名

### `configs/collection/rd/profiles/`

这里放可被实际选择和执行的 RD collection profile。

它们回答的问题是：

- 这一轮采什么
- 默认 metadata 怎么填
- 默认绑定哪份 mmWave cfg
- gesture / environment 允许值有哪些
- 每个 gesture 的 target duration 大概多久

放在这里的 profile 应满足：

- `lifecycle = "active"`
- 会进入 `vassago collection rd list-configs`
- 可以被 `init-session --config-id ...` 直接消费

### `configs/collection/rd/companions/`

这里放可复用的 background collection policy，也就是 companion profile。

当前 companion profile 主要描述：

- `default_recording_duration_multiplier`
- 各 background `collection_type` 的 `sample_ratio`

它不是主 profile 的替代物，而是补充背景采集策略的可复用组件。

当前典型绑定链路是：

1. profile 通过 `default_companion_profile_id` 绑定一个 companion
2. `init-session` 在创建 background session 时根据它展开 `background_plan`
3. manifest 顶层保留 `companion_profile_id`

什么时候应该新建 companion profile：

- 你需要复用一套 background 录制时长 / sample ratio 策略
- 这套策略不应硬编码在某一个 profile 里

### `configs/collection/rd/templates/`

这里放脚手架模板，不放实际给协作者执行的 active 配置。

规则很简单：

- 模板文件放这里
- metadata 里的 `lifecycle` 应为 `template`
- 它们会进入 catalog，但不应被业务入口当成 active profile 使用

典型用途：

- 新 profile 的起手式
- 稳定字段布局参考
- 注释化的作者说明

## 4. 最常见的放置判断

### “我要新增一轮 RD 手势采集配置”

放到：

- `configs/collection/rd/profiles/`

起手文件：

- 复制 `configs/collection/rd/templates/rd_template.toml`

### “我要给 background session 增加另一套切片采样策略”

放到：

- `configs/collection/rd/companions/`

同时：

- 让目标 profile 的 `default_companion_profile_id` 指向它

### “我要新增一份板卡 bring-up / collection 共用的 mmWave cfg”

放到：

- `configs/firmware/mmwave/`

然后：

- 跑 `vassago configs validate`
- 必要时补 `mmwave_cfg_integrity`

### “我要改 discovery 或 cfg 校验规则”

放到：

- `configs/registry/`

不要放到：

- `src/` 里的常量散落处
- 某个 profile 注释里

## 5. 不建议进入 repo-managed config 的内容

下面这些东西，当前不建议直接写进正式 `configs/`：

- 某台电脑临时探测出来的串口名
- 只服务于个人调试、且不会复用的本地 override
- 运行期中间产物
- 某次 session 的 manifest 或导出结果

它们更适合留在：

- CLI 交互输入
- 本机未纳管文件
- `data/`

例外情况：

- 固定实验台、固定串口映射且团队明确接受耦合时，profile 可以带默认串口；但这应该是少数场景，不是默认做法

## 6. 编辑后最少要跑什么

改完 `configs/` 之后，最少做这两步：

1. 运行全量配置校验

```bash
uv run vassago configs validate
```

2. 补一条真实业务消费命令验收

例如：

```bash
uv run vassago collection rd list-configs
uv run vassago firmware mmwave smoke-test --help
```

如果你改的是 background profile / companion 绑定，建议再补：

```bash
uv run vassago collection rd init-session --help
```

## 7. 一句话总结

放配置时，先判断“属于哪个业务域”，再判断“属于哪个角色目录”。

当前仓库里：

- 板级 `.cfg` 去 `firmware/mmwave/`
- RD 运行时基线去 `collection/rd/global.toml`
- 可执行 profile 去 `collection/rd/profiles/`
- background 策略去 `collection/rd/companions/`
- 模板去 `collection/rd/templates/`
- 治理规则去 `registry/`
