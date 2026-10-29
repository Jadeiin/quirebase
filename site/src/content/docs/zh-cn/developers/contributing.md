---
title: 开发与维护文档
description: 启动开发检出，找到工程约定，并让行为变更和文档在同一改动中交付。
---

公开页面说明用户和运维任务；`GLOSSARY.md`、ADR 和架构契约定义工程术语与不变量。
改变行为前，应先阅读对应契约。

## 启动开发应用

准备 Git、Python 3.12+、uv 0.13.5+、Bun 1.4.4，然后执行：

```sh
git clone https://github.com/Jadeiin/quirebase.git
cd quirebase
./scripts/dev.sh
```

脚本安装依赖、初始化开发数据，首次设置时创建用户名 `admin`、密码 `quirebase-dev` 的用户，并启动：

| 服务 | 默认地址或作用 |
| --- | --- |
| Vite | `http://127.0.0.1:5173`，带热更新的浏览器应用 |
| FastAPI | `http://127.0.0.1:9060`，HTTP API |
| Worker | 使用同一开发数据处理持久化后台任务 |

部署实例请使用[安装流程](/zh-cn/administration/deployment/)，设置自己的管理员密码。
仓库 [README](https://github.com/Jadeiin/quirebase/blob/main/README.md#development)提供手动设置和 `QUIREBASE_DEV_*` 覆盖选项。

## 运行仓库检查

安装 hooks：

```sh
uv run --frozen prek install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
```

构建应用前端后，运行后端测试和 pre-push 检查：

```sh
bun install --cwd frontend --frozen-lockfile
bun run --cwd frontend build
uv run ruff check .
uv run mypy src/quirebase
uv run pytest -q -m "not oa" -n 4 --dist loadscope
```

PostgreSQL、并发、可选依赖和单独下载的开放 PDF 语料，见[测试指南](https://github.com/Jadeiin/quirebase/blob/main/docs/TESTING.md)。

## 预览和检查文档

文档项目还需要 Node.js 22.23.4+，并有独立的 Bun 锁定依赖：

```sh
uv sync --frozen
bun install --cwd site --frozen-lockfile
bun run --cwd site dev
```

文档开发服务器独立运行，打开 Astro 输出的本地地址即可预览。
修改后执行：

```sh
bun run --cwd site check
bun run --cwd site build
bun run --cwd site preview
```

Pagefind 搜索在构建后生成，可在 preview 中检查。
检查会覆盖中英页面配对、内容结构、站内链接，以及最终 HTML 资源和 API 覆盖。
[维护说明](https://github.com/Jadeiin/quirebase/blob/main/site/README.md)记录写作策略和仅生成产物的 CI。
GitHub Pages 发布仍在后续独立变更中处理。

## 把变更写进对应文档

| 改变了什么 | 更新哪里 |
| --- | --- |
| 用户流程或界面名称 | 对应的中英任务指南 |
| 运维配置、部署、恢复 | 对应操作流程 |
| 路由描述或 Schema 约束 | FastAPI 源码，由它生成 API 参考 |
| 领域术语或关系 | [术语表](https://github.com/Jadeiin/quirebase/blob/main/GLOSSARY.md) |
| 架构与不变量 | [ADR](https://github.com/Jadeiin/quirebase/tree/main/docs/adr) 和 [契约](https://github.com/Jadeiin/quirebase/tree/main/docs/architecture) |

[模块归属](https://github.com/Jadeiin/quirebase/blob/main/docs/architecture/modules.md)规定能力及依赖边界。
[Agent 指南](https://github.com/Jadeiin/quirebase/blob/main/AGENTS.md)记录迁移生成等仓库特定要求。
API 参数表应保持自动生成；手写教程应解释完整任务，再链接到对应参考。
