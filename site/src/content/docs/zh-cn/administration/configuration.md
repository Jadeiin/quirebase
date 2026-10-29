---
title: 配置实例
description: 分清配置优先级，建立可运行的基础配置，再设置数据库、来源、文件存储和客户端访问。
---

Web 和 Worker 应配置为同一个实例。开始前，先分清“进程启动配置”和“管理员在应用中保存的运行时设置”。

## 确认哪个值真正生效

| 来源 | 在哪里设置 | 如何生效 |
| --- | --- | --- |
| 部署环境 | 进程环境变量，或工作目录中的 `.env` | 进程环境变量优先于 `.env`；修改后重启相关进程 |
| Compose 环境 | `.env.docker` 和 `docker-compose.yml` | 用 `make docker-up` 应用；Compose 还提供数据库和数据目录默认值 |
| 运行时设置 | 管理员页面的“设置”（Settings） | 对支持的字段，数据库中保存的值覆盖部署默认值 |

支持运行时覆盖的内容包括注册策略、额外工作区创建策略、来源联系方式及凭据、会话时长、上传字节上限和导出保留时长。
修改 `.env` 后这些值没有变化时，应先查看管理员设置页显示的实际值。
数据库连接、对象存储后端、外部 Origin 和 Worker 身份仍属于部署设置。

## 建立本地基础配置

源码运行时，在执行 `uv run quirebase …` 的目录创建 `.env`：

```dotenv
QUIREBASE_DATABASE_URL=sqlite:///./quirebase.db
QUIREBASE_DATA_DIR=./quirebase-data
QUIREBASE_ALLOWED_HOSTS=localhost,127.0.0.1
QUIREBASE_EXTERNAL_ORIGIN=http://127.0.0.1:9060
QUIREBASE_SECURE_COOKIES=false
INQUIRO_CONTACT_EMAIL=operator@example.org
```

请换成你维护的联系邮箱。这份配置用于本机 HTTP 访问；公网 HTTPS 应使用[部署说明](/zh-cn/administration/deployment/)中的实际域名、Origin 和安全 Cookie。
相对文件路径从进程工作目录解析，所以 Web 与 Worker 的工作目录也要一致。

## 选择数据库和加入策略

| 设置 | 应用默认值 | 用途 |
| --- | --- | --- |
| `QUIREBASE_DATABASE_URL` | `sqlite:///./quirebase.db` | SQLite 文件或 PostgreSQL libpq URL |
| `QUIREBASE_DATA_DIR` | `./quirebase-data` | 应用持久化数据目录 |
| `QUIREBASE_REGISTRATION_POLICY` | `invitation_only` | 账号注册方式：`open`、`closed`、`invitation_only` |
| `QUIREBASE_WORKSPACE_CREATION_POLICY` | `admins_only` | 创建额外工作区：`admins_only` 或 `members_allowed` |
| `QUIREBASE_WORKFLOW_EXECUTOR_ID` | `quirebase-worker` | 稳定的 Worker 身份，每个 Worker 必须不同 |

表中是应用默认值，Compose 的具体配置可能不同。账号创建时自动获得的工作区，不受“额外工作区创建”策略阻止。
有运行时策略覆盖时，以管理员设置页的生效值核对。源码使用 PostgreSQL 前，应安装 `postgres` 可选依赖。

## 配置外部来源和引文支持

通过 `INQUIRO_CONTACT_EMAIL` 提供来源识别用的联系邮箱。
可选凭据包括 `INQUIRO_NCBI_API_KEY`、`INQUIRO_OPENALEX_API_KEY`、`INQUIRO_NASA_ADS_TOKEN`、`INQUIRO_IEEE_API_KEY`。
部分来源必须有凭据；应用会显示当前可用的查找和搜索来源。排查时要同时检查管理员保存的运行时值和环境默认值。

内置引文样式需要 `citation` 可选依赖，源码环境可执行 `uv sync --frozen --extra citation`。
同步时保留其他需要的 extras，例如同时传入 `--extra postgres`。Docker 镜像已包含 PostgreSQL 和引文 extras。
有权限的用户也可以添加自定义样式。

标签推荐默认使用离线 YAKE。可选本地 KeyBERT 引擎需要安装 `keybert` extra，设置
`QUIREBASE_RECOMMENDATION_ENGINE=keybert`，并让 `QUIREBASE_KEYBERT_MODEL_PATH` 指向管理员预先准备的本地 Model2Vec 目录。
不支持运行时下载模型或直接填写远程模型标识符。

## 设置文件存储和大小上限

本地对象位于 `QUIREBASE_DATA_DIR/objects`。使用 S3 兼容存储时，设置：

```dotenv
QUIREBASE_OBJECT_STORE=s3
QUIREBASE_S3_BUCKET=your-bucket
QUIREBASE_S3_REGION=your-region
```

同时为 Web 和 Worker 配置适用的 endpoint、prefix 及原生 AWS 凭据。
改配置不会复制旧对象；切换已有实例前，应保持物理对象键不变地迁移文件。
S3 需要单独的备份方案，`quirebase backup` 仅支持本地对象存储。

PDF 和附件的默认单文件上限都是 `262144000` 字节，即 250 MiB。
设置名为 `QUIREBASE_MAX_PDF_BYTES`、`QUIREBASE_MAX_ATTACHMENT_BYTES`，也可能被管理员运行时设置覆盖。
这里填写字节数，不是直接填写 MiB 数值；反向代理的请求大小上限也要协调。

只在容器网络可见的 S3 域名应继续使用应用流式下载。直接签名下载需要浏览器可达的地址，并单独配置存储桶 CORS。
endpoint、签名和迁移的完整要求见[对象存储契约](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#object-storage)。

## 浏览器 MCP 客户端

原生 MCP 客户端通常不发送 Origin。浏览器客户端需要明确配置 `QUIREBASE_MCP_ALLOWED_ORIGINS` 白名单。
它只控制 MCP CORS，与 HTTP API 的浏览器 Origin 策略、S3 存储桶 CORS 分别配置。

完成配置后，按[维护指南](/zh-cn/administration/maintenance/)使用相同实例设置运行健康与恢复检查。
