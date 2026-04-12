# 开发教程索引

`docs/dev/tutorials/` 保存稳定、可重复执行的开发规范与教程。

这里不保存某一次项目调查本身，只保存以后仍然适用的规则和流程。

## AI 必读

如果你是 AI coding agent，开始改代码前至少先读这两份：

- [development-workflow.md](development-workflow.md)
  约束工作流和提交边界。
- [reusable-code-index.md](reusable-code-index.md)
  约束优先复用仓库现有代码，避免平行复制逻辑和制造屎山。

这两份应被视为同等重要。

## 当前文档

- [environment-setup.md](environment-setup.md)
  本地开发环境初始化。
- [development-workflow.md](development-workflow.md)
  开发工作流、commit checkpoint 和 conventional commit 规范。
- [reusable-code-index.md](reusable-code-index.md)
  仓库可复用代码索引。新增代码前，先确认已有模块是否已经覆盖需求。
- [configs-directory-guide.md](configs-directory-guide.md)
  `configs/` 目录结构、人类可读的编辑边界与文件放置规则。
- [configs-command-guide.md](configs-command-guide.md)
  `configs` 相关命令指南，覆盖文件发现、配置消费与全量验证。
- [collection-toml-authoring.md](collection-toml-authoring.md)
  RD collection profile TOML 编写说明书。
- [collection-qc-guide.md](collection-qc-guide.md)
  RD collection 的 `quick_qc`、`metadata_qc`、`offline-qc` 使用与排障说明。
