# Advanced Alchemy 后续接入研究

基于原型提交 `7e4d2e7`、锁定的 **AA 1.11.0** 源码与追加 SQLite 探针。
这份研究没有修改应用行为或初始迁移。底层行为证据在
[extension_evidence.json](extension_evidence.json)，可以重跑：

```sh
uv run --frozen python scripts/advanced_alchemy/extension_probe.py
```

探针使用现有 User、Item、Attachment、Author 的实际映射和表；UniqueMixin 使用同一 Author
表的替代映射，加密字段使用独立研究表。全部数据库和对象位于临时目录。
它验证库的接入边界，尚未实现下文建议的新增完整产品用例。

## 优先级

| 优先级 | 能力 | 项目中的具体落点 | 收益 |
| --- | --- | --- | --- |
| P0 | `EngineConfig` + AA JSON serializer | `core.database.make_async_engine` | 让 engine、session、JSON 配置共同由 AA 配置管理；消除 engine-instance 路径绕过 JSON defaults 的缺口。 |
| P0 | `JsonB` + 原生 dict/list 字段 | ImportBatch、AuditEvent、ItemTagRecommendation、FileRevision.page_geometry、Item.custom_fields、ObjectIntegrityScan.errors | 删除持久字段的手工 encode/decode、字符串默认值和重复 JSON 解析；PostgreSQL 使用 JSONB，SQLite 使用 JSON。 |
| P0 | 扩大 `StoredObject` / `FileObject` | FileRevision 原件与缩略图，随后 ExportArtifact | Documents 的文件描述、下载投影、统计、清理与 integrity scan 使用共同的数据形状。 |
| P1 | read repositories + filters + `OffsetPagination` | Audit 查询、Annotations page 查询、Projects/Workspaces directory、成员/讨论列表 | 完成分页产品闭环，统一响应结构与过滤；限制大列表的传输和渲染成本。 |
| P1 | `EncryptedString` / `EncryptedText` | 现有 NASA ADS、OpenAlex、NCBI、IEEE 凭据 | 给已经存在的 Provider credential 增加密文存储。需要明确的凭据记录与部署密钥。 |
| P2 | `ResultConverter`、细分数据库异常 | 简单 Admin/Accounts DTO 和实际采用 Repository 的写入边界 | 收敛简单 projection 转换与跨数据库错误分类；复杂授权 projection 继续由业务模块生成。 |

**下一轮推荐顺序：JSON 配置与结构化字段 → PDF/缩略图文件模型 → directory 分页闭环 →
Provider credential 加密。** 这四项分别有具体的重复代码、已有文件用例、产品体验和已有凭据
作为落点，可以继续在当前真实应用原型上验证。

## 1. engine 配置还没有用完整

当前 `make_async_engine` 直接调用 SQLAlchemy `create_async_engine`，再将 engine 传给 AA。
`SQLAlchemyAsyncConfig(engine_instance=...)` 无法回头将 `EngineConfig` 的 JSON serializer
defaults 应用到已创建的 engine。

追加探针发现：同一份包含 native UUID 的 JSON payload，经当前 engine 写入 JsonB 会抛出
TypeError；由 AA `EngineConfig` 创建的 engine 可以 roundtrip。JSON 中的 UUID 读回是字符串，
不能把 `Mapped[list[UUID]]` 当成自动恢复 UUID 元素的声明。

建议让 engine factory 使用 AA config 创建 engine，保留已有 libpq URL 规则、SQLite FK/WAL
监听器、pool pre-ping 和 `expire_on_commit=False`，不改变事务归属。所有 app/test/migration
engine 通过同一个 factory 创建。DBOS 自身的数据库配置继续按它的接口管理。

AA 的 JSON 编码器也有适用边界：当前环境直接 `encode_json(OffsetPagination[Pydantic DTO])`
会得到字符串表示；经 FastAPI `jsonable_encoder` 后正确。数据库 JSON 值应先变成明确的
基础 dict/list，API 使用 Pydantic/FastAPI 的已声明 schema 序列化。

## 2. JSON 字段是剩余最大的重复实现之一

统计现有 `src/quirebase`，有 **55 处** `json.loads` / `json.dumps`，分布在 **20 个文件**。
其中包括协议与导出编码，不能全部删除；持久字段相关的部分是这次接入目标。

首批建议：

- `ImportBatch.records / errors / committed_item_ids`：保留 preview、准备、确认、重试、discard
  的状态机和对象 reservation 规则；将存储值改成 list/dict。完整用例覆盖 worker 重启、确认
  幂等返回、失败后重试、授权撤销与 staged PDF 清理。
- `AuditEvent.detail / target_ids`：直接存结构化值，避免 API 再解析。detail 保留 dict/string
  的明确语义；全文模糊搜索需显式 cast 或改为 JSON path，不能继续直接调用字符串 `.ilike`。
- `ItemTagRecommendation.single_words / phrases`、`ObjectIntegrityScan.errors`、
  `FileRevision.page_geometry` 与 `Item.custom_fields`：直接使用已有 domain value 的 JSON 形状。
- `PdfAnnotation.payload` 已是普通 JSON，可以统一为 `JsonB`，避免各模块自己选择方言 variant。

Item 的 authors、keywords、urls 当前有文本检索/缓存语义；canonical `ItemIdentifier` 也已有
独立关系。它们需要各自的数据设计，不能根据字段里出现 JSON 就一并改成数组或增加第二份事实。

`JsonB` 负责存储，不负责校验任意 Python 字典是否符合业务 schema。边界上的 domain validation
仍需保留。更新采用整体替换值，和现有 CAS/锁/业务审计一起完成。

**不建议为 ImportBatch.records 套 AA `MutableList`。** 探针确认，替换 list 中的 dict 会因为
其内部 removed-set 要求 hashable 而抛 TypeError；它也没有递归追踪嵌套 dict 的语义。
有必要时可选 SQLAlchemy 的相应 mutable 类型，但这里整体替换能更直接保持快照写入规则。

新 schema 继续按用户确认的 breaking-change 方案生成并收进唯一初始迁移，不引入旧数据转换。

## 3. FileObject 可以继续扩到整个 Documents 模块

Attachment 现在已采用完整文件模型；FileRevision 还维护以下描述字段：
`object_key / size / mime_type / original_name / thumbnail_object_key / thumbnail_size`。
可以收敛为 `file: FileObject` 和 `thumbnail: FileObject | None`。

`page_count / page_geometry / full_text / processing_state` 是 PDF 领域数据，继续作为 FileRevision
的数据。这样 PDF 原件与附件可以共用文件 descriptor、统计、ZIP/copy、对象引用收集和清理逻辑。
ExportArtifact 随后也可采用同一 descriptor，同时保留 workflow_id 自然键与 expires_at。

追加探针发现一个必须落实的写入语义：

- 文件 listener 关闭时，`attachment.file.update_metadata(...)` 后 commit 不会保存元数据变化。
- 即使赋一个新的 FileObject，只要路径和 backend 相同，AA 的 FileObject equality 仍认为它们
  相等，因此 ORM dirty comparison 同样可能不发 UPDATE。
- 实际 Attachment 上执行明确的 `update(...).values(file=descriptor)` 可以正确保存。

建议统一使用显式 SQL 值替换来处理 descriptor 的补全和 repair，并验证 AuditColumns timestamp、
回滚及业务 AuditEvent。如果以后新增交互式文件 metadata 编辑，再评估专门的 compare_values。
这不是重新打开默认文件 listener 的理由：之前已验证它无法承担 durable upload 提交顺序。

`FileObjectList` 可以用于没有独立身份的文件集合；现有 Attachment 有自己的 ID、role、作者与
生命周期，仍应保留独立行。

## 4. 分页需要把服务端与用户恢复流程一起收完

AA 1.11.0 有 `LimitOffset`、`OrderBy`、`BeforeAfter`、`ComparisonFilter`、`CollectionFilter`、
`SearchFilter` 和 `OffsetPagination`。没有现成的完整 keyset/cursor paginator；可以用 comparison
filter 构建 cursor 条件，但 next_cursor、额外取一条、总数语义仍由当前用例定义。

直接可收敛的是 Audit 查询和 Annotations 的 page 查询，它们仍手工维护 offset/count。
Root SQL 的授权与 discoverability predicate 在所有 filters 和 count 前建立。

Projects/Workspaces 的 API 目前没有分页，收益包含产品体验：

- Project directory 先分页 Project roots，再按这一页 ID 批量加载 item counts 与 participation，
  避免将 grouped、多列 projection 塞给 QueryRepository。之前的实测已经确认其 count 限制。
- Workspace directory 先分页 roots，再按页面 IDs 获取 membership/owner projection。
- 当前 Workspace 没出现在第一页面时，前端通过 `GET /workspaces/{id}` 解析当前上下文；chooser
  分页不能被当成可访问 Workspace 的全集。
- Managed Project 的治理 discoverability 与 `mine` participation 分开处理。
- Annotations 的 total 表示完整授权集合；cursor 条件不应无意缩小这个 total。
- 统一一个分页响应契约后，同时更新 OpenAPI、客户端 queries 与分页控件，避免留两套 envelope。

这些不是 Repository 或 Filter 的默认行为，需要继续用完整 HTTP/前端用例证明。

## 5. Provider credential 加密有现成的产品落点

运行时设置现在将已有 API keys/tokens 放在 `SystemSetting.value` Text 中。
AA `EncryptedString` 已在追加 SQLite 探针验证：原始 SQL 读到密文，重新构造加密类型并重新打开
engine 后可以读取原值。

建议将凭据与一般 runtime setting 分开，采用固定密钥 callable 的加密字段，直接接入
`get_effective_settings_model` 和 ProviderRuntime；声明 AA `cryptography` extra。
界面可以提供 configured/替换/清除状态，减少回显已保存的密钥。

这项主要收益是保护现有凭据。所有 API/worker/maintenance 进程必须使用相同部署密钥；
密钥恢复与轮换也需要明确。AA 默认随机密钥不能用于持久部署。
Alembic 应将底层类型 render 为 SQL Text，不能把运行时密钥写入 autogenerate 输出。

## 6. Repository 写入与其他 mixin 的真实边界

**可以继续评估 Repository 写入，并按具体 command 决定。** `add_many` 会使用现有 session
批量添加并 flush；`upsert_many` 探针确认 `auto_commit=False` 后调用方 rollback 仍有效。对需要默认时间、UUID、
异常分类的简单创建，它可以复用当前 Repository 配置。

不过 `upsert_many` 在锁定的 1.11.0 实现里先查询、分拆新旧行，再 add/update，并不是数据库
`ON CONFLICT DO NOTHING`。实际 Author 探针也确认匹配已有身份后会更新其它字段。它不能直接
替代幂等 additive association：重复关联应保持原记录与作者，并且不能多记一条业务事件。
批量 create 的效率本身主要来自 SQLAlchemy，换方法名并不证明减少 roundtrip。

`UniqueMixin` 在实际 Author 表上有两个实测结果：

- 同一个 session 内重复请求会返回同一个对象，适合单事务内去重。
- rollback 后再次调用会拿到 transient 的旧缓存对象；两个独立 session 先读再创建也仍会发生
  uniqueness conflict。当前 `find_or_create_author` 的 savepoint/reselect 仍有实际作用。

因此如要采用 UniqueMixin，需要解决缓存事务寿命，而不能删掉数据库约束和并发冲突处理。
当前 Author 用例没有足够的减负理由直接替换它。

`ResultConverter` 已用实际 User 和 `AdminUserView` 验证，可把简单 DTO 转成 OffsetPagination，
DTO 字段白名单也不包含 password_hash。Workspace/Project 的 authorization 与 concrete choices
继续由现有 projection 生成；Converter 不替代这些事实计算。

AA 的 DuplicateKeyError / ForeignKeyError / CheckConstraintError 可以在采用 Repository 的写入
边界映射成既有 domain errors。需要同步调整现有 raw IntegrityError catches；Web 不应直接
将所有数据库异常改成一个状态码。

## 可以带来新产品能力的后续选项

| 能力 | 合理用例 | 当前判断 |
| --- | --- | --- |
| `TOTPSecret` / `TOTPProvider` | 登录 MFA | 可用的值类型基础；还需 enrollment、challenge、恢复码、replay 状态与 session 流程。当前未安装 pyotp，未实测。 |
| `OneTimeCode` | 邮箱验证码、密码恢复验证码 | 提供 hash/expiry/attempts/used-state 值模型；redeem 返回待保存的状态，并发单次消费仍需要锁或 CAS，hash 仍需线程边界。现有高熵邀请 token 没有因此替换的必要。 |
| FileObject signed URL | S3 大文件直接传输 | 可以减少应用数据转发；签名后有效期内不逐请求重新检查 Workspace 权限，还需将直接上传接回现有 receipt/finalizer。当前没有 S3 runtime 验证。 |
| `Vector` | Item/PDF 语义检索 | 类型支持按方言选 pgvector 或 JSON fallback；还需要 embedding 生成、索引、更新/删除 workflow 和 Workspace 过滤。JSON fallback 不提供同等向量检索能力。 |
| 读写 routing、dogpile cache | 读副本或特定慢读模型 | 有真实部署需求后评估；当前查询规模未证明收益，授权与最终写入读取必须使用有效的 canonical state。 |
| FastAPI extension / service providers | app lifespan、dependency、engine/session 统一管理 | 可采用 manual 模式，但当前 get_db 与 lifespan 很短，而且 CLI/DBOS/MCP 也共享配置，暂时收益小于 JSON/文件/分页。 |
| SlugKey、CLI/Alembic wrapper | 人类可读 URL、复杂多 bind 运维 | 当前 UUID 路由、单 schema 和少量 Alembic 调用已足够直接；未找到具体减负落点。 |

安装版本的 mixin 清单中也没有通用 SoftDelete/Version/CAS mixin，不能把项目的 archive/delete
生命周期或乐观并发方案当成可直接替换的 AA 能力。

来源：[AA 官方文档](https://advanced-alchemy.litestar.dev/latest/)、
[AA 源码](https://github.com/litestar-org/advanced-alchemy)，以及当前锁定版本的本地源码。
所有追加运行时观察来自 SQLite；PostgreSQL、S3 和 MFA 的未验证范围分别标注在上文。
