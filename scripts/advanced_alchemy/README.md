# Advanced Alchemy 完整用例原型

原型分支：`prototype/advanced-alchemy-use-cases`。问题是：Advanced Alchemy 1.11.0
能否承担真实实体、密码和文件的持久化，以及授权查询的分页，从而减少 Quirebase 的维护代码？
这个分支已经修改实际应用、领域服务、模型、初始迁移和生成的前端契约。

结论：`UUIDv7AuditBase`、UTC 日期类型、Argon2 值模型、附件文件模型和只读分页 Repository
值得采用。采用它们仍需要明确的协议转换、数据库存储类型和 durable 文件提交顺序。
这里没有测量吞吐或索引性能；UUIDv7 的性能收益需要另做基准。

## 运行

在这个分支的仓库根目录运行：

```sh
uv run --frozen python scripts/advanced_alchemy/use_cases.py
```

它自动创建标记为 `quirebase-aa-PROTOTYPE-*` 的临时目录，运行实际 `init-db`、HTTP
应用、独立 DBOS worker、LocalStore，最后运行 `doctor`。不读取现有数据库或对象存储凭据。
退出时停止 worker，保留临时数据库和 worker 日志，便于查看。机器可读结果保存在
[use_case_evidence.json](use_case_evidence.json)。需要可用的本地回环连接。

补充底层行为探针：

```sh
uv run --frozen python scripts/advanced_alchemy/probe.py
```

结果保存在 [evidence.json](evidence.json)。[demo.html](demo.html) 可以直接打开，
展示分页、Workspace 恢复和 Project participation 的交互语义；它使用模拟页面状态。
完整 API、密码、文件和 worker 的验证由上面的 `use_cases.py` 完成。

## 实际接入

| 能力 | 实现与效果 |
| --- | --- |
| UUID 与审计基础类 | 24 个实体继承实际 `UUIDv7AuditBase`，删除重复 PK、`created_at`、`updated_at` 声明。所有实体关系使用 Python UUID 与 AA GUID；SQLite 存 16 字节 BLOB，PostgreSQL 使用 native UUID。 |
| 自然键与不可变记录 | `LoginThrottle`、`ItemRead`、`ItemTag`、`ExportArtifact`、`SystemSetting` 保留自然键或复合主键；`AuditEvent` 和 `PdfAnnotationObject` 使用 `UUIDv7Base`。审计事件只有创建时间，不增加可变更新时间。 |
| 审计时间 | `AuditColumns` 的 default/onupdate 支持 ORM 与 Core DML；所有日期改用 `DateTimeUTC`，移除 `as_utc` 修补逻辑。显式业务时间仍可覆盖。业务 `AuditEvent` 与实体在同一事务提交/回滚。 |
| Session 配置 | 实际 `AsyncSessionLocal` 由 AA `SQLAlchemyAsyncConfig` 创建，共用现有 engine、31 表 metadata、事务边界和 SQLite PRAGMA。 |
| 密码 | `User.password_hash` 使用 AA `HashedPassword`、Argon2Hasher 与 PasswordHash 类型。验证、准备哈希和重哈希移到线程边界；登录重哈希用 SQL CAS，避免覆盖并发密码修改。 |
| 文件 | `Attachment.file` 使用 AA `StoredObject` / `FileObject`，统一路径、大小、MIME 和原始文件名。旧附件标量字段已删除，上传、下载、ZIP、复制、删除、统计与完整性扫描直接读取文件模型。 |
| 对象存储 | 真实 LocalStore/S3Store 注册为 AA `ObstoreBackend`；附件和 PDF 上传走 `FileObject.save_async`。有界流式校验、Range、HEAD、列表与下载继续使用 obstore 的流接口。 |
| 分页 | 实际 Items 与管理员 Users 查询使用模块内部 AA `SQLAlchemyAsyncRepository` / `LimitOffset`，完整授权 SQL 在 count 和分页前应用，稳定排序，并使用独立 count 保留空页总数。 |
| Workflow | DBOS 参数和结果保留 native UUID，JSON attributes 统一序列化。文档实体用 UUIDv7，文件与缩略图拥有独立 UUIDv4 对象 ID。 |
| 维护扫描 | 完整性扫描成为具有 UUIDv7 的历史记录，删除硬编码 `id="latest"` 的覆盖逻辑。 |
| 初始迁移 | 按用户要求只保留一个初始版本，包含 UUID、审计列、sentinel、文件 JSON/JSONB 与搜索结构；从 AA metadata 实际 autogenerate 后合入初始 revision 的函数体。不提供旧数据库转换路径。 |
| 前端契约 | 重新生成 OpenAPI TypeScript；可选 Project UUID 查询省略空字符串，避免未选择过滤器时收到 422。 |

客户端为 Annotation/Reply 提供的 UUIDv4 仍是当前创建协议的一部分；服务端实体默认使用
UUIDv7。UUIDv7 不作为文件分片 ID：探针中连续生成的 256 个 UUIDv7 只有一个对象键前缀，
因此文件继续使用独立随机对象 ID。

## 可重复验证的真实用例

- 注册、登录、错误密码、修改密码、私密账户投影；单次哈希持久化，弱参数哈希登录升级，
  第二连接在验证过程中修改密码时不会被登录重哈希覆盖。
- API 创建 27 个 Items；第 1/2/空页分别返回 25/2/0 条，空页仍有总数 27；外部用户无法读取，
  Workspace 过滤在分页和计数前生效；Users 空页总数和系统授权也正确。
- API/Core SQL 修改更新时间、创建时间稳定、显式时间不被覆盖、UTC roundtrip，以及实体和
  业务审计事件共同回滚。
- 先停止 worker，再实际上传附件并保存 durable receipt；重启独立 worker 后成功 finalize。
  验证文件模型、文档投影、下载、ETag、外部用户拒绝、ZIP、跨 Workspace 独立对象复制和删除。
- 实际 PDF 处理、全文/Range/缩略图读取；无效图片 worker 失败后清理独立对象。
- 实际创建 Annotation 和 Reply、cursor 分页、worker 导出带标注 PDF、下载和 requester 授权。
- 使用实际 Attachment mapping 与受控失败 backend 观察 AA 默认文件监听器：数据库提交先返回，
  上传尚未完成时另一连接已能看到行，文件保存失败后行仍然存在。
- 新数据库 `init-db` 和 `doctor` 的数据库、对象、workflow、对象完整性和领域完整性检查。

## AA 行为边界

1. **文件监听器关闭。** AA 1.11.0 的异步文件监听器安排 post-commit 保存，不能承担现有
   上传对象、durable receipt、授权重检、数据库 finalize 的顺序。对象存储无法参加数据库事务，
   原型使用真实 AA 文件模型/backend，并保留应用的 durable workflow 与清理逻辑。
2. **密码使用准备后的值。** 默认 PasswordHash 在 ORM bind 时同步计算字符串哈希；原型的小型
   `PreparedPasswordHash` 保存线程中准备的 `HashedPassword`，避免事件循环阻塞和二次哈希，
   并支持编码后的哈希用于 SQL CAS 比较。
3. **全局更新时间监听器关闭。** mixin 的 onupdate 已覆盖 ORM/Core 更新。全局 listener 会
   干扰显式时间赋值，原型验证保留覆盖语义。
4. **SQLite GUID 编译为 BLOB。** AA 默认的 `BINARY(16)` 会被 SQLite 反射为 `NUMERIC(16)`。
   BLOB 保持相同 UUID 字节，并使初始迁移、metadata 和 Alembic 反射一致。
5. **Repository 只处理明确的读模型。** AA window count 在空页返回 0，原型采用独立 count。
   多列、grouped Project 投影的 QueryRepository 计数不适用，保留显式 SQL。Repository 上的
   默认 scoped statement 也不能被当作批量写入的租户防线。

## 架构边界与验证范围

ADR 0006 拒绝通用 Repository/UoW，原因是它们容易复制事务所有权。这次原型是在该决策上
验证一个具体例外：Items/Users 的只读 Repository 位于能力所属模块，接收现有 session，
不拥有 commit，不成为对外接口。授权仍由 Access 拥有；Casbin、行锁、乐观版本、SQL CAS、
业务写入与 DBOS recovery 仍有明确的所属模块。采纳主分支时需要据此修订 ADR 的例外说明。

Projects/Workspaces 的实际 API 仍返回完整 directory；这里只在底层探针验证其分页与查询
形状。Annotations 已有 page/cursor API，此分支验证了 UUID 接入后的真实调用。
这次原型没有完成所有 directory 的产品分页改造。

SQLite 的初始迁移、upgrade/downgrade roundtrip、schema parity 和 autogenerate 无差异
均已执行。PostgreSQL 的初始迁移及查询 SQL 已离线编译；当前没有 PostgreSQL 服务，
运行时迁移、JSONB 聚合、跨连接锁和并发测试尚未执行。NanoID extra 未在当前环境完成安装，
没有声称验证它。

完整验证结果见 [verification.json](verification.json)：后端 fast suite **1042 passed / 88 skipped**，
前端 **114 passed**，Svelte 检查 0 errors / 0 warnings，Ruff、142 个源文件的 mypy、
锁文件检查和 OpenAPI 类型重复生成通过。跳过项包括未配置的 PostgreSQL 与外部测试数据；
它们没有被计入运行时验证结论。

后续能力的源码研究、优先级和追加行为探针见
[further-adoption.md](further-adoption.md)。该研究没有改变应用行为或 schema。
