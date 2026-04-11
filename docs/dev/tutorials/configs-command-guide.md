# `configs` 相关命令使用指南

这篇文档是写给“要发现配置文件、确认 `config_id`、验证配置树、或让业务命令消费某份配置”的人看的。

它不讲实现细节，重点只放在“现在该跑什么命令”。

## 1. 先建立一个正确心智模型

和 `configs/` 打交道时，命令大致分成 3 类：

1. 找文件
2. 验配置
3. 用配置

大多数排查都应该按这个顺序走，而不是一上来就猜代码。

## 2. 找文件：先确认仓库里到底有什么

### 看整个 `configs/` 树里有哪些受关注文件

```bash
rg --files configs
```

适合场景：

- 你刚接手仓库
- 你只记得文件大概在 `configs/` 下，但忘了具体位置
- 你想确认某个文件到底在不在 repo 里

### 只看 mmWave cfg

```bash
rg --files configs/firmware/mmwave
```

适合场景：

- 想找可用的 `.cfg`
- 想确认新加的 cfg 是否已经落在正确目录

### 只看 RD collection 相关 TOML

```bash
rg --files configs/collection/rd
```

适合场景：

- 想确认 `global.toml`、`profiles/`、`templates/` 现在有哪些文件

## 3. 找身份：快速确认 `config_id`

很多时候你真正要找的不是文件名，而是 `config_id`。

### 在 `configs/` 里搜索 `config_id`

```bash
rg -n "config_id = " configs
```

适合场景：

- 你知道配置用途，但忘了它的 `config_id`
- 你想确认有没有重复或相似命名

### 看某个文件头部 metadata

例如：

```bash
sed -n '1,20p' configs/firmware/mmwave/baseline_pointcloud.cfg
```

或：

```bash
sed -n '1,20p' configs/collection/rd/profiles/rd_phase1_default.toml
```

重点看：

- `config_kind`
- `config_id`
- `label`
- `description`
- `lifecycle`

## 4. 看发现规则：为什么某个文件会或不会被 catalog 发现

如果你怀疑“文件明明在仓库里，但命令就是没认出来”，先看 discovery rule。

```bash
sed -n '1,200p' configs/registry/catalog_roots.toml
```

这份文件决定：

- 哪些 glob 会被纳入 catalog
- 每个 glob 对应什么 `kind`

典型场景：

- 新文件放错目录了
- 新增了模板，但没落在被发现的 glob 下
- 你以为某个目录会被 catalog 扫到，其实没有

## 5. 验配置：改完后先跑全量校验

### 全仓配置校验

```bash
uv run python -m vassago.configs.validation
```

这是修改 `configs/` 之后最重要的一条命令。

它会统一检查：

- metadata header 能不能解析
- `config_id` 有没有重复
- lifecycle 和目录角色是否冲突
- mmWave cfg 命令是否合法
- RD collection global/profile 能不能正常加载

什么时候必须跑：

- 新增或修改任何 `configs/` 文件之后
- 修改 `catalog_roots.toml` 之后
- 修改 `mmwave_cfg_commands.toml` 之后

### 跑配置相关测试

```bash
uv run pytest tests/test_configs.py
```

适合场景：

- 你改了 config validator 或 config loader
- 你想多拿一层回归保障

如果你改动涉及 collection profile，也建议补跑：

```bash
uv run pytest tests/test_collection_config.py tests/test_collection_session.py
```

## 6. 用配置：确认业务命令真的能消费它

校验通过不代表业务入口一定按你预期消费了它，所以改完后最好再跑一条“真实消费命令”。

### 查看当前可选 collection profiles

```bash
uv run vassago collection rd list-configs
```

这条命令适合验证：

- `configs/collection/rd/profiles/*.toml` 是否真的被业务入口识别
- `label`、`description` 是否对人可读
- 你的 profile 有没有被错误写成 template 或无效配置

### 用某个 `config_id` 初始化 collection session

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

这条命令适合验证：

- profile 的 `config_id` 能不能被解析
- `global` 和 `firmware` 绑定是否有效
- `defaults` / `options` / `gesture_target_durations` 是否能被正常消费

### 用某个 mmWave `config_id` 做 smoke-test

```bash
uv run vassago firmware mmwave smoke-test \
  --config-id baseline_pointcloud \
  --cli-port /dev/ttyXXX \
  --data-port /dev/ttyYYY \
  --no-interactive
```

这条命令适合验证：

- mmWave cfg 是否真的能被 `config_id` 解析到
- cfg 文件本身是否至少能进入真实消费链路

## 7. 常见排查顺序

### 场景 1：命令里说找不到 `config_id`

按这个顺序看：

1. `rg -n "config_id = " configs`
2. `sed -n '1,20p' <目标文件>`
3. `sed -n '1,200p' configs/registry/catalog_roots.toml`
4. `uv run python -m vassago.configs.validation`

最常见原因通常是：

- 文件放错目录
- metadata header 写错
- `config_id` 不在被发现的目录树下

### 场景 2：文件在，但 `list-configs` 看不到

优先检查：

- 文件是不是放在 `profiles/` 而不是 `templates/`
- `lifecycle` 是否写成了 `template`
- 文件是否能通过 `uv run python -m vassago.configs.validation`

### 场景 3：校验器报 mmWave cfg 错误

优先看：

```bash
sed -n '1,240p' configs/registry/mmwave_cfg_commands.toml
```

通常是：

- 命令名不在 registry 里
- 参数个数不对
- `sensorStart` 不是最后一条
- 某些派生约束不满足

### 场景 4：你只是想快速确认改动没把配置树搞坏

最省心的最小命令集合是：

```bash
uv run python -m vassago.configs.validation
uv run vassago collection rd list-configs
uv run pytest tests/test_configs.py
```

## 8. 什么时候该用 shell 命令，什么时候该用业务命令

最简单的判断标准：

- 只是找文件、看 metadata、看 registry
  用 `rg`、`sed`
- 想验证仓库配置系统整体是否 still valid
  用 `uv run python -m vassago.configs.validation`
- 想确认业务流程是否真的能消费某份配置
  用 `vassago collection rd ...` 或 `vassago firmware mmwave ...`

不要把这三类命令混成一类。

## 9. 一句话总结

和 `configs/` 打交道时，最稳妥的顺序永远是：

1. 先找文件
2. 再看 `config_id`
3. 再跑全量校验
4. 最后跑真实消费命令

这样排查，通常比一上来猜 loader 或猜 CLI 快得多。
