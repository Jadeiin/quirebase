---
title: 备份、升级与故障恢复
description: 停止正确的写入进程，生成可验证的离线备份，恢复数据，并接续持久化任务。
---

所有命令都必须使用目标实例的数据库、数据目录和对象存储配置。
源码示例使用 `uv run quirebase`，发行包安装使用自己的 `quirebase` 可执行程序。
Compose 示例面向默认的本地对象存储服务组合。

## 先检查健康状态

源码运行执行 `uv run quirebase doctor`，Compose 执行 `make docker-doctor`。
命令应以退出码 0 完成并显示 `[ok]` 诊断；出现 `[failed]` 时，应先排查，再认为升级或重启已经完成。

Doctor 检查数据库和结构访问、工作流存储、可写目录、PDF 支持、推荐引擎、对象存在性及大小、工作区和项目完整性。
它不会逐个计算对象内容哈希。管理员维护页面可以查看清理结果和工作流状态。

## 备份本地对象存储

备份前必须停止**所有 Web 和 Worker 写入进程**。数据库与对象分开复制；多 Worker 实例只停掉其中一个，仍不属于离线备份。
归档应放在数据目录和可重建卷之外。每次保留备份使用新的文件名，不要覆盖唯一一份已经验证的副本。

### 源码实例：创建并验证

停止 Web 和 Worker 后，从安装目录执行：

```sh
uv run quirebase backup ../quirebase-backup.zip
uv run quirebase verify-backup ../quirebase-backup.zip
```

**核对结果：** 两条命令均成功结束，目标路径存在归档。
其中包含 SQLite 快照或 PostgreSQL dump、本地不可变对象和数据库校验清单。
验证检查数据库校验和及归档路径，不是逐个对象的内容校验。备份成功后再启动 Web 和 Worker，并将独立副本保留到安装主机之外。

### Compose：把验证后的归档复制到宿主机

停止默认 Web、Worker 及额外 Worker，保持 PostgreSQL 运行。
在源码目录执行以下操作，保留备份容器，直到归档复制出来：

```sh
mkdir -p backups
docker compose --env-file .env.docker stop web worker
docker compose --env-file .env.docker run --name quirebase-backup --no-deps web sh -c 'quirebase backup /tmp/quirebase.zip && quirebase verify-backup /tmp/quirebase.zip'
docker cp quirebase-backup:/tmp/quirebase.zip ./backups/quirebase.zip
docker rm quirebase-backup
docker compose --env-file .env.docker start web worker
```

必须先确认归档已复制成功，再删除备份容器。备份报错时先处理错误，不要继续当作成功备份。
再次运行前，示例容器名需要处于可用状态；宿主机目标文件也应改为每次独立的保留文件名。
验证后的副本还应复制到安装主机之外。

### 恢复并核对内容

先在独立实例演练恢复。停止目标写入进程，确认数据库和本地对象目录指向准备替换的目标，并验证归档。
源码目标可以执行：

```sh
uv run quirebase verify-backup ../quirebase-backup.zip
uv run quirebase restore ../quirebase-backup.zip --force
uv run quirebase doctor
uv run quirebase reindex
```

`--force` 会替换配置指向的数据库并恢复归档对象，执行前务必核对目标设置。
Compose 恢复也应使用相同镜像、配置和数据卷的一次性服务，并让归档在容器内可访问；不要在仍提供 Web 服务的进程旁直接恢复。
检查成功后再启动服务，并核对登录、代表性条目、文件读取和保存过的批注。

S3 需要独立备份或版本保护策略，`quirebase backup` 会拒绝非本地对象存储。
内置 Garage 只有一个节点且没有存储桶版本控制，详细操作见[卷快照流程](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#object-storage)。

## 升级实例

1. 阅读目标版本对数据库和持久化工作流的说明。
2. 停止全部 Web、Worker，在可替换卷之外创建并验证备份。
3. 安装匹配版本的 Quirebase、Inquiro、Excerpo；源码安装还要用该检出的依赖重新构建前端，Compose 则构建或选择目标镜像。
4. 使用现有实例配置运行目标版本的 `quirebase init-db`。
5. 运行 Doctor，重启 Web 和 Worker，再检查登录及文件处理。

Alpha 版本可能要求重建数据库并重新导入内容，不应假定旧的持久化工作流格式兼容。
数据库改变后，回滚需要匹配备份，不能只降级包版本。
详细[升级说明](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#upgrades)记录了包括 DBOS 存储变更在内的具体过渡要求。

## 接续持久化任务

使用同一个稳定 executor ID 重启 Worker，可以接续它原先正在执行的任务。
如果某个 executor 已永久退役，先检查，再应用恢复：

```sh
uv run quirebase recover-workflows OLD_EXECUTOR_ID
uv run quirebase recover-workflows OLD_EXECUTOR_ID --apply
```

把 `OLD_EXECUTOR_ID` 换成真正退役的身份。恢复任务不意味着可以让两个活跃 Worker 共用一个 ID。
工作流历史最终会按保留期清理，清理后无法再恢复执行。

## 保留期与数据库空间

| 设置 | 默认值 | 控制什么 |
| --- | --- | --- |
| `QUIREBASE_ANNOTATION_UNDO_HOURS` | 24 小时 | 普通批注、回复的撤销窗口 |
| `QUIREBASE_WORKFLOW_HISTORY_RETENTION_DAYS` | 7 天 | 已完成工作流历史 |
| `QUIREBASE_TERMINAL_METADATA_RETENTION_DAYS` | 30 天 | 凭据、邀请、成员关系等终态元数据 |
| `QUIREBASE_AUDIT_RETENTION_DAYS` | 90 天 | 审计事件 |
| `QUIREBASE_IMPORT_BATCH_RETENTION_DAYS` | 7 天 | 临时导入批次历史 |

清理导入历史会保留已创建条目和文件，但不再支持回执重放和批次筛选。
这些值不代表自动删除研究内容、用户账号或备份。
删除行可能只让数据库空间可复用，不会立即缩小文件。
SQLite 压缩要先停止所有写入进程，再执行 `quirebase compact-sqlite`；PostgreSQL 的空间维护另行处理。
