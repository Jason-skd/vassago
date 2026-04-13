# `configs` 命令使用指南

这篇文档是写给“要发现配置、跑全量检测、单独执行某个子检查，或确认业务命令真的能消费某份 config”的人看的。

本文以当前 `vassago configs` 命令树为准。

## 1. 先建立正确心智模型

当前 `configs` 系统分成 4 层：

- catalog discovery
  负责发现 `configs/` 下哪些文件属于 repo-managed config，并解析 metadata header。
- validation orchestrator
  负责把 discovery 和多个 peer checks 串起来，形成一次全量校验。
- peer checks
  每个子检查都可以被独立调用，目前至少包括：
  - entry location
  - config semantics
  - mmWave cfg integrity
- business consumers
  例如 `collection rd init-session`、`collection rd list-configs`、`firmware mmwave smoke-test`。

一句话记忆：

- `vassago configs list`
  看 catalog 里现在到底有什么
- `vassago configs validate`
  跑全量检测
- `vassago configs validate-*`
  只跑某个重要子检查
- `collection` / `firmware` 命令
  验证业务入口是否真的能消费这些 config

## 2. 先看 catalog：仓库现在发现到了什么

### 列出全部受管 config

```bash
uv run vassago configs list
```

适合场景：

- 你刚接手仓库
- 你想确认某份配置有没有进入 catalog
- 你怀疑某个文件在仓库里，但 discovery 没把它认出来

### 只看某一类 config

例如只看 mmWave cfg：

```bash
uv run vassago configs list --kind mmwave_cfg
```

例如只看 active 的 RD collection profile：

```bash
uv run vassago configs list \
  --kind collection_rd_profile \
  --lifecycle active
```

这类命令适合回答：

- 某个 `config_id` 是否真的在 catalog 里
- 某个 profile 是否被错误标成 template
- 现在有哪些 active / template 配置

## 3. 跑全量检测：默认入口就是 `configs validate`

### 全仓配置检测

```bash
uv run vassago configs validate
```

这是修改 `configs/` 之后最重要的一条命令。

它会按统一编排依次做这些事：

1. 跑 discovery
2. 构建 catalog
3. 运行 entry location 检查
4. 运行语义检查
5. 运行 mmWave cfg integrity 检查

当前它覆盖的核心问题包括：

- metadata header 无法解析
- `config_kind` 与 discovery root 不一致
- `config_id` 重复
- lifecycle 与目录角色冲突
- header-only key 被写进 TOML body
- mmWave cfg 命令名、参数个数、顺序或派生约束错误
- collection global / profile 无法加载
- mmWave cfg integrity registry 与当前 catalog 不一致

什么时候必须跑：

- 新增或修改任何 `configs/` 文件之后
- 修改 `configs/registry/catalog_roots.toml` 之后
- 修改 `configs/registry/mmwave_cfg_commands.toml` 之后
- 修改 config loader / validator / catalog builder 之后

### 全量检测和严格 integrity 检查的区别

默认：

```bash
uv run vassago configs validate
```

会先为“registry 里还没有记录的新 mmWave cfg”追加 hash，再继续全量检测。

如果你想要一个不自动补记录、只做严格校验的入口，用：

```bash
uv run vassago configs validate-mmwave-cfg-integrity
```

如果你确认就是要把新 cfg 纳入 registry，再显式运行：

```bash
uv run vassago configs record-missing-mmwave-cfg-integrity
```

## 4. 单独跑子检查：不要总是把所有问题混在一起

### 只检查 discovery / metadata

```bash
uv run vassago configs validate-discovery
```

这条命令只关注：

- `catalog_roots.toml` 能不能加载
- discovery root 是否可用
- metadata header 能不能解析
- `config_kind` 是否和 root 对得上
- `config_id` 是否重复

适合场景：

- 新文件刚落到 `configs/`，但你还没开始排正文
- 命令里说找不到 `config_id`
- 你怀疑文件路径或 metadata header 写错了

### 只检查 lifecycle / 目录角色

```bash
uv run vassago configs validate-entry-location
```

这条命令只关注：

- active config 是否误放在 `templates/`
- template config 是否误放在 active 目录

适合场景：

- `list` 能看见文件，但业务入口没把它当 active 配置
- profile / template 目录边界刚改过

### 只检查 config semantics

```bash
uv run vassago configs validate-semantics
```

这条命令只关注 catalog 已经发现成功之后的正文语义：

- TOML body 里是否误写 header-only key
- mmWave cfg 是否满足命令表与派生约束
- RD collection global / profile 是否能被 loader 正常消费

适合场景：

- 你已经确认文件能被发现
- 现在要排“正文结构不合法”而不是 discovery 问题

### 只检查 mmWave cfg integrity

```bash
uv run vassago configs validate-mmwave-cfg-integrity
```

这条命令只关注：

- integrity registry 是否缺项
- registry 是否声明了未知 `config_id`
- 当前 cfg 内容 hash 是否与 registry 一致

适合场景：

- 你在处理 mmWave cfg 变更
- 你想确认某次改动是不是触发了受管 cfg 漂移
- 你不想在检查前自动补 registry

## 5. 修 registry：只在你明确知道自己在做什么时运行

### 为新 mmWave cfg 补 hash

```bash
uv run vassago configs record-missing-mmwave-cfg-integrity
```

它只会：

- 发现 catalog 里的 mmWave cfg
- 找出 integrity registry 里还没有记录的 `config_id`
- 只追加这些缺失项

它不会：

- 刷新已有 hash
- 覆盖旧记录
- 帮你“接受”已存在 cfg 的内容变化

如果某个已有 cfg 内容真的变了，优先判断：

- 这是不是不该直接修改的受管 cfg
- 是否应该新建一个新的 `config_id`

## 6. 改完后还要跑业务入口验收

`configs validate` 通过，不代表业务命令就一定按你预期消费了配置。

至少再补一条真实消费命令。

### 验证 collection profile 是否被识别

```bash
uv run vassago collection rd list-configs
```

适合检查：

- `profiles/*.toml` 是否真的进入 active selection
- `label` / `description` 是否对人可读
- profile 是否误写成 template

### 验证 collection profile 是否能初始化 session

```bash
uv run vassago collection rd init-session \
  --config-id rd_phase1_default \
  --subject-name skd \
  --gesture swipe_left \
  --environment office_lab \
  --operator-name your_name \
  --radar-id rd_aop_01 \
  --firmware-id rd_phase1_uart \
  --cli-port /dev/ttyXXX \
  --data-port /dev/ttyYYY \
  --no-interactive
```

适合检查：

- profile 的 `config_id` 能不能被解析
- `global` 和 `firmware` 绑定是否有效
- runtime / defaults / options 是否能被业务流程正常消费

### 验证某个 mmWave cfg 是否能进入真实消费链路

```bash
uv run vassago firmware mmwave smoke-test \
  --config-id baseline_pointcloud \
  --cli-port /dev/ttyXXX \
  --data-port /dev/ttyYYY \
  --no-interactive
```

适合检查：

- mmWave cfg 是否真的能通过 `config_id` 解析
- cfg 文件是否至少能走到业务链路里

## 7. 常见排查顺序

### 场景 1：命令里说找不到 `config_id`

按这个顺序看：

1. `uv run vassago configs list`
2. `uv run vassago configs validate-discovery`
3. `uv run vassago configs validate`

最常见原因通常是：

- 文件放错目录
- metadata header 写错
- `config_id` 不在被 discovery 的目录树下

### 场景 2：文件在，但业务入口看不到它

优先检查：

1. `uv run vassago configs list --kind collection_rd_profile`
2. `uv run vassago configs validate-entry-location`
3. `uv run vassago collection rd list-configs`

最常见原因通常是：

- 文件在 `templates/` 而不是 active 目录
- `lifecycle = "template"`
- 语义检查没过，业务 loader 没法消费

### 场景 3：全量检测里主要是 mmWave cfg 报错

优先拆开跑：

1. `uv run vassago configs validate-semantics`
2. `uv run vassago configs validate-mmwave-cfg-integrity`
3. `uv run vassago configs record-missing-mmwave-cfg-integrity`

经验上：

- 语义报错先修 cfg 正文
- integrity 缺项再补 registry
- 已有 cfg hash mismatch 不要直接“补记录覆盖过去”

### 场景 4：你只是想确认这次改动没把配置树搞坏

最省心的最小命令集合是：

```bash
uv run vassago configs validate
uv run vassago collection rd list-configs
uv run pytest tests/test_configs.py
```

## 8. 什么时候还该用 shell 命令

`vassago configs` 已经覆盖 discovery、全量检测和重要子检查。

但下面这些动作，shell 仍然合适：

- 想看某个文件头部 comment metadata
  用 `sed -n '1,20p' <path>`
- 想看 registry 原文
  用 `sed -n '1,240p' configs/registry/*.toml`
- 想在大范围内搜某个字段
  用 `rg`

判断标准很简单：

- 想执行 repo 约定好的检查流程
  先用 `vassago configs ...`
- 想人工阅读原文或做低层排查
  再用 `rg` / `sed`

## 9. 一句话总结

和 `configs/` 打交道时，默认顺序是：

1. `uv run vassago configs list`
2. `uv run vassago configs validate`
3. 需要时再拆成 `validate-discovery` / `validate-semantics` / `validate-mmwave-cfg-integrity`
4. 最后补一条真实业务消费命令验收

这样排查，通常比直接猜 loader、猜 CLI、猜 registry 快得多。
