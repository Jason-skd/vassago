# `configs/` 目录结构指南

这篇文档是写给“准备新增、修改或排查仓库配置文件的人”看的。

目标只有两个：

- 让你快速看懂当前 `configs/` 目录为什么这样组织
- 让你知道一个文件应该放哪里，不该放哪里

如果你接下来还要写 RD collection profile，可以继续读 [collection-toml-authoring.md](collection-toml-authoring.md)。

## 1. 先建立一个正确心智模型

`configs/` 不是随手堆文件的草稿箱。

它是当前仓库的“repo-managed config tree”，也就是：

- 文件会被代码按规则发现
- 文件会被 metadata header 识别
- 文件会被校验器做结构和语义检查
- 业务流程会按 `config_id` 消费这些文件

所以这里最重要的不是“路径长什么样”，而是“路径、metadata 和业务含义必须一致”。

一句话记忆：

- 目录负责表达角色
- metadata 负责表达身份
- `config_id` 负责给代码引用

## 2. 当前目录结构怎么读

当前仓库里的 `configs/` 主要长这样：

```text
configs/
├── collection/
│   └── rd/
│       ├── global.toml
│       ├── profiles/
│       │   └── *.toml
│       └── templates/
│           └── *.toml
├── firmware/
│   └── mmwave/
│       └── *.cfg
└── registry/
    ├── catalog_roots.toml
    └── mmwave_cfg_commands.toml
```

可以把它分成 3 个层次：

1. 业务配置
2. 固件配置
3. 配置系统自己的 registry

## 3. 每个子目录分别负责什么

### `configs/firmware/mmwave/`

这里放 repo-managed 的 mmWave `.cfg` 文件。

它们的用途是：

- 被 `smoke-test` 按 `config_id` 选择并下发
- 被 `collection` session 绑定和复用
- 被 config validator 检查命令形状与派生约束

放在这里的文件应该满足：

- 真的是要被仓库长期管理的 `.cfg`
- 顶部带有 `% --- vassago:meta ---` 结构化头
- `config_kind = "mmwave_cfg"`

### `configs/collection/rd/global.toml`

这里放 RD collection 的仓库级 baseline。

它负责的是“整类 RD 采集默认怎么跑”，例如：

- `capture_window_duration_s`
- `countdown_duration_s`
- `marked_window_end_grace_s`
- `end_mark_key`
- 默认串口波特率

它不是某一次采集 session 的运行结果，也不是某一轮 profile 的私有副本。

### `configs/collection/rd/profiles/`

这里放正式可选用的 RD collection profile。

它们负责的是：

- 本轮采集叫什么
- 绑定哪份 global baseline
- 绑定哪份 mmWave cfg
- 本轮支持哪些手势和环境
- 每个 gesture 的 target duration 是多少

对 operator 来说，这里就是“可选 profile 列表”的来源。

### `configs/collection/rd/templates/`

这里放模板文件。

它们的目标不是直接运行，而是：

- 给新 profile 提供起步骨架
- 让字段顺序、metadata 头和常见默认值保持稳定

最简单的理解方式：

- `profiles/` 是准备给人选用的
- `templates/` 是准备给人复制的

### `configs/registry/catalog_roots.toml`

这是“配置发现规则表”。

它告诉 catalog：

- 哪些 glob 应该被当成受管理配置
- 每个 glob 对应什么 `ConfigKind`

如果你想知道“为什么某个文件会被发现”或“为什么某个文件根本没进 catalog”，先看这里。

### `configs/registry/mmwave_cfg_commands.toml`

这是 mmWave cfg 命令 registry。

它定义：

- 哪些命令允许出现
- 每个命令允许多少个参数
- 最少/最多出现次数
- 是否必须出现在最后
- 某些命令是否应该只给 warning

如果你想修改 mmWave cfg 校验口径，先看这里，而不是先改 Python 校验代码。

## 4. 新文件应该放哪里

如果你现在要新增的是：

- 一份新的 mmWave `.cfg`
  放到 `configs/firmware/mmwave/`
- 一份新的正式 RD collection profile
  放到 `configs/collection/rd/profiles/`
- 一份给别人复制的 RD profile 模板
  放到 `configs/collection/rd/templates/`
- RD collection 的仓库级默认值
  改 `configs/collection/rd/global.toml`
- 配置发现规则
  改 `configs/registry/catalog_roots.toml`
- mmWave cfg 允许命令集合
  改 `configs/registry/mmwave_cfg_commands.toml`

如果一个文件不知道该放哪，通常意味着它的角色还没有想清楚。

## 5. 目录结构里最容易搞混的 4 组概念

### `global.toml` 和 `profiles/*.toml`

区分方式：

- `global.toml` 负责仓库级基线默认值
- `profiles/*.toml` 负责某一轮采集意图

不要把 global 的字段整段复制进每个 profile 只为了“看起来完整”。

### `profiles/` 和 `templates/`

区分方式：

- `profiles/` 里的文件是给运行流程直接消费的
- `templates/` 里的文件是给人复制出新配置的

目录语义应和 metadata lifecycle 对齐：

- active 文件不该长期放在 `templates/`
- template 文件不该长期放在正式 `profiles/`

### `firmware.config_id` 和磁盘路径

区分方式：

- 业务层优先通过 `config_id` 绑定 mmWave cfg
- 真正的路径解析由 catalog 和 loader 处理

不要在 profile 里写 `config_path`。

### metadata header 和 TOML 正文

区分方式：

- `config_id`、`label`、`description`、`lifecycle` 属于 header
- 运行时配置字段属于正文

不要把 header-only key 再写进 TOML body。

## 6. 每个受管理配置文件都应满足什么

当前仓库的受管理配置文件，至少要满足：

- 文件一开始就有结构化 metadata header
- `config_kind` 正确
- `config_id` 稳定且唯一
- `label` 和 `description` 对人可读
- `lifecycle` 与目录角色一致

mmWave `.cfg` 用 `%` 注释头，TOML 用 `#` 注释头。不要混用。

## 7. 最稳妥的编辑顺序

如果你准备改 `configs/`，最稳妥的顺序通常是：

1. 先确定这份文件属于哪个目录角色
2. 再确定 `config_kind`、`config_id`、`lifecycle`
3. 再改正文内容
4. 最后跑全量验证

也就是先定身份，再定内容，不要反过来。

## 8. 改完后最少要做什么检查

至少做下面两件事：

1. 跑全量校验

```bash
uv run python -m vassago.configs.validation
```

2. 如果你改的是 collection profile 或 mmWave cfg，再跑对应消费命令确认它真的还能被业务流程读到

例如：

```bash
uv run vassago collection rd list-configs
```

或：

```bash
uv run vassago firmware mmwave smoke-test --help
```

## 9. 一句话总结

读 `configs/` 时，不要只把它当目录树。

它其实是：

- 一套稳定的角色分层
- 一套 metadata 约束
- 一套会被代码发现、校验和消费的正式配置系统

如果你把文件放对了目录、写对了 metadata，并且优先通过 `config_id` 让业务流程引用它，后面的维护成本会低很多。
