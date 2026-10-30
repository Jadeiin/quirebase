---
title: 备份、升级与故障恢复
description: 停止正确的写入进程，生成可验证的离线备份，恢复数据，并接续持久化任务。
---

使用目标实例的数据库、数据目录和对象存储配置运行以下命令。
源码示例使用 `uv run quirebase`，发行包安装使用自己的 `quirebase` 可执行程序。
Compose 示例面向默认的本地对象存储服务组合。

## 先检查健康状态

源码运行执行 `uv run quirebase doctor`，Compose 执行 `make docker-doctor`。
命令应以退出码 0 完成并显示 `[ok]` 诊断；出现 `[failed]` 时，应先排查，再认为升级或重启已经完成。

Doctor 检查数据库和结构访问、工作流存储、可写目录、PDF 支持、推荐引擎、对象存在性及大小、工作区和项目完整性。
管理员维护页面可以查看清理结果和工作流状态。

## 备份本地对象存储

备份前停止**所有 Web 和 Worker 写入进程**，以便一致地复制数据库与对象文件。
归档放在数据目录和可重建卷之外，每次备份使用独立文件名。

### 源码实例：创建并验证

停止 Web 和 Worker 后，从安装目录执行：

```sh
uv run quirebase backup ../quirebase-backup.zip
uv run quirebase verify-backup ../quirebase-backup.zip
```

**核对结果：** 两条命令均成功结束，目标路径存在归档。
其中包含 SQLite 快照或 PostgreSQL dump、本地不可变对象和数据库校验清单。
验证检查数据库校验和及归档路径。备份成功后再启动 Web 和 Worker，并将独立副本保留到安装主机之外。

### Compose：把验证后的归档复制到宿主机

先停止额外的 Worker，保持 PostgreSQL 运行。在源码目录执行以下脚本，
它会停止默认 Web、Worker，并为每次备份创建独立目录和归档文件名。
括号让脚本在子 Shell 中运行；即使整块粘贴到交互式终端，`set -eu` 也会在出错时停止执行。

以下示例使用 Docker。使用 Podman 时，将 `docker compose` 换成 `podman compose`
（独立提供程序使用 `podman-compose`），将 `docker cp` / `docker rm` 换成 `podman cp` / `podman rm`。
Makefile 命令的引擎选择见[容器引擎选择](/zh-cn/administration/deployment/#容器引擎选择)。

```sh
(
  set -eu
  mkdir -p backups
  backup_dir=$(mktemp -d "./backups/quirebase-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
  backup_container=$(basename "$backup_dir")
  backup_archive="$backup_dir/$backup_container.zip"
  printf 'Container: %s\nArchive: %s\n' "$backup_container" "$backup_archive"

  docker compose --env-file .env.docker stop web worker
  docker compose --env-file .env.docker run --name "$backup_container" --no-deps web sh -c 'quirebase backup /tmp/quirebase.zip && quirebase verify-backup /tmp/quirebase.zip'
  docker cp "$backup_container:/tmp/quirebase.zip" "$backup_archive"
  docker rm "$backup_container"
  docker compose --env-file .env.docker start web worker
)
```

验证并复制归档成功后，脚本才会删除备份容器并重启写入服务。
备份、验证或复制失败时，备份容器会保留，写入服务保持停止。
根据输出的容器名和归档路径排查；复制失败可能留下不完整的宿主机文件。
解决问题并成功验证、复制归档后，再手动删除该容器并启动 Web、Worker。
将验证后的副本复制到安装主机之外。

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
Compose 恢复时，停止 Web 和 Worker，再使用相同镜像、配置和数据卷的一次性服务，让归档在容器内可访问。
检查成功后再启动服务，并核对登录、代表性条目、文件读取和保存过的批注。

本节的 `backup` 命令用于本地对象存储。S3 实例需要备份数据库和对象存储，内置 Garage 可按[卷快照流程](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#object-storage)操作。

## 升级实例

1. 阅读目标版本对数据库和持久化工作流的说明。
2. 停止全部 Web、Worker，在可替换卷之外创建并验证备份。
3. 安装匹配版本的 Quirebase、Inquiro、Excerpo；源码安装还要用该检出的依赖重新构建前端，Compose 则构建或选择目标镜像。
4. 使用现有实例配置运行目标版本的 `quirebase init-db`。
5. 运行 Doctor，重启 Web 和 Worker，再检查登录及文件处理。

按目标版本的[升级说明](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#upgrades)处理数据库和持久化工作流变更。
需要回滚时，安装备份对应的版本并恢复该备份。

## 接续持久化任务

使用同一个稳定 executor ID 重启 Worker，可以接续它原先正在执行的任务。
如果某个 executor 已永久退役，先检查，再应用恢复：

```sh
uv run quirebase recover-workflows OLD_EXECUTOR_ID
uv run quirebase recover-workflows OLD_EXECUTOR_ID --apply
```

把 `OLD_EXECUTOR_ID` 换成退役的身份。每个运行中的 Worker 使用自己的稳定 ID；任务可在工作流历史的保留期内恢复。

## 保留期与数据库空间

| 设置 | 默认值 | 控制什么 |
| --- | --- | --- |
| `QUIREBASE_ANNOTATION_UNDO_HOURS` | 24 小时 | 普通批注、回复的撤销窗口 |
| `QUIREBASE_WORKFLOW_HISTORY_RETENTION_DAYS` | 7 天 | 已完成工作流历史 |
| `QUIREBASE_TERMINAL_METADATA_RETENTION_DAYS` | 30 天 | 凭据、邀请、成员关系等终态元数据 |
| `QUIREBASE_AUDIT_RETENTION_DAYS` | 90 天 | 审计事件 |
| `QUIREBASE_IMPORT_BATCH_RETENTION_DAYS` | 7 天 | 临时导入批次历史 |

清理导入历史会保留已创建条目和文件，但不再支持回执重放和批次筛选。
清理释放可复用的数据库空间。需要缩小 SQLite 文件时，先停止所有写入进程，再执行 `quirebase compact-sqlite`；PostgreSQL 的空间维护另行处理。
