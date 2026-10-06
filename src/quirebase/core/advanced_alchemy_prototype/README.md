# Advanced Alchemy、UUIDv7 与分页：可丢弃原型

问题：Quirebase 如果补齐有序 UUID 主键与列表分页，Advanced Alchemy 能否减少维护，
同时保留 Workspace 授权、Project discoverability、参与投影和显式事务？

结论：**UUIDv7 与分页值得推进。AA 的类型与日期组件有实际价值，但 1.11.0 的通用
repository 分页不能直接承接现有目录投影。当前证据支持局部选用组件；不足以支持
全仓改为 repository/service 架构。**

此分支只保存实验、证据与结论。生产依赖、模型、API、前端和 Alembic 链均未修改。
原型源码位于数据库模块旁边，禁止从生产入口导入。

## 运行

双击同目录的 `demo.html`，无需服务器、安装依赖或联网。四个引导场景可重复运行，
也可自由操作。界面状态为内存模拟；初始可发现性与参与状态来自真实后端查询，
HTML 内嵌一次运行的证据，按钮不会调用后端。

从原型分支的仓库根目录重新运行数据库探针：

```sh
uv run --frozen --with 'advanced-alchemy[uuid]==1.11.0' python src/quirebase/core/advanced_alchemy_prototype/backend.py
```

这会创建内存 SQLite，执行探针并刷新 `evidence.json` 与 HTML 内嵌证据。
使用当前冻结的项目依赖，AA 仅在 uv 的临时依赖环境中加入。不会连接配置的数据库，
也不修改生产依赖清单或 lockfile。命令已在独立 uv 环境运行成功。

## 实际观察

| 实验 | 结果 | 对落地的影响 |
| --- | --- | --- |
| 沿用现有 engine、metadata、session | 成功，FastAPI 配置可使用 manual commit | 不必迁移到 Litestar，也不必交出事务所有权 |
| 原生 SQLAlchemy `Uuid` + uuid7 | UUID 版本 7；SQLite CHAR(32)，PostgreSQL UUID | 有序 ID 不依赖 AA Base；生成器和列类型可以分别决策 |
| AA `UUIDv7AuditBase` | 版本 7；SQLite BINARY(16)，PostgreSQL UUID；Python 为 UUID | 紧凑存储可用，但 base 还带来命名约定和 `sa_orm_sentinel` 列 |
| 日期往返 | AA 保留 UTC；普通 SQLite DateTime(timezone=True) 返回 naive datetime | `DateTimeUTC` 是明确的维护收益，不能只按 CRUD 行数评价 AA |
| UUID 复合外键 | 合法关联成功；错 Workspace 的关联被拒绝 | UUID 类型可保留当前 lineage 防线 |
| 显式 CAS / 审计回滚 | 首次修改成功、同版本再次修改失败；回滚同时撤销实体与 AuditEvent | 现有共享 session 的事务方案可以保留；此处为顺序执行，未验证 PG 并发 |
| 授权后分页 | Admin 总数 6；Editor 5；Admin mine 3 | SQL 过滤须在 count 与 limit 前，治理可发现不等于参与 |
| 默认窗口计数的空页 | 默认 total=0，独立计数 total=6 | 单模型 repository 使用 `count_with_window_function=False`；空页应有明确 API 契约 |
| 当前 Workspace 不在第一页 | 第一页 Alpha；直接解析 Gamma 成功 | 恢复逻辑应直接确认访问，不能用一页 Workspace 列表推断 membership |
| 删除游标边界并编辑下一条 | keyset 返回下一条；offset 跳过下一条 | cursor 携带不可变排序值 + ID，不依赖边界记录仍存在 |
| 有过滤的 repository 批量更新 | 返回 0 行，但另一 Workspace 的记录已被修改 | 读取 statement 不构成写入授权边界；保留显式写谓词与 Access 检查 |
| 真实目录多列 / GROUP BY 投影 | 查询可返回 Project、Item count、participation；通用 list/count 不可直接用 | 需要显式投影和子查询计数，见下文 |

完整输出见 `evidence.json`，其中包含 SQLite/PostgreSQL DDL、锁和 CAS SQL。
这些不是基准测试，也没有用 UUID 的排序性质代替产品排序或跨进程的严格时间序。
独立 count 和数据查询在 READ COMMITTED 下也不保证同一快照。

## 两个维护成本不能忽略

现有 Project directory 返回 `Project + count(ProjectItem) + is_participating`，不是一个
裸模型列表。原型创建了 2 个 Item、3 个 ProjectItem 来验证这个真实查询形状。
AA 1.11.0 的 `SQLAlchemyAsyncQueryRepository.get_many` 能原样读取，但
`get_many_and_count` 的窗口路径出现 `ValueError: too many values to unpack`，
基本计数路径对 GROUP BY 出现 `MultipleResultsFound`。显式
`count(*) FROM (完整过滤后的分组查询)` 返回正确总数 6。该 QueryRepository 版本的
计数标志方向也与模型 Repository 不一致，原型中已注释。

因此，把所有 list 改成 AA 的 list/count 调用不能消除这些业务查询。普通单模型分页
只省去两条直接 SQL；cursor、授权过滤、聚合计数、投影和数据契约仍需项目维护。
现有映射虽然运行兼容，AA 的 `ModelProtocol` 泛型边界在当前 mypy 下也不能直接接受
Project/Workspace；原型仅在两处使用有说明的窄范围忽略。生产选用 repository 前要
解决这个类型契约，而不是批量隐藏类型问题。

NanoID 的 `fastnanoid==0.4.3` 在本机 Python 3.14/macOS arm64 需要原生源码构建；
缺少 Rust 后自动安装工具链的过程又因构建环境的 SOCKS 支持缺失而失败。
这是本机安装失败，不能据此断言其他环境不支持。未执行 NanoID 运行验证。
不装 extra 时 AA 会退回 uuid4，名称不保证实际格式。
Python 3.12 下 UUIDv7 也应显式安装 `[uuid]`，避免缺生成器时退回 uuid4。

## 建议的生产改进边界

1. **数据库实体采用 UUIDv7**：生成器、SQLAlchemy UUID 列、API 字符串表示分别选择。
   AA GUID/DateTimeUTC 可以独立评估，不要求所有 31 个模型继承 AA Base。
   采用 UUID 列时 FK、复合键与迁移一起处理；继续沿用现有 Alembic 链并新增 revision。
   默认生成器切换与已有 ID 重写是不同工作，UUIDv7 无需强行重写历史标识。
2. **补齐 Projects / Workspaces 分页，统一分页契约**：筛选在服务端分页前完成，
   限制页大小、稳定排序有唯一 ID tie-breaker，空页保留有效总数。
   目录分类可按已有 `view` 独立查询，或清楚地呈现部分 `all` 结果。
   当前 Workspace 的恢复使用直接授权解析，与选择器分页分开。
3. **保留 Items / Annotations 现有分页能力**：Items 已有页码分页，Annotations 已有
   页码和 ID cursor。价值在统一契约、排序与边界行为；AA 没有替代这些 keyset 语义。
   此原型实际执行的是 Projects/Workspaces 代表性切片，未迁移 Items/Annotations API。
4. **按实证选 AA 组件**：优先比较 UTC 类型、GUID 与 offset 参数/响应容器；
   复杂投影继续显式 SQL，现有 Access、锁、CAS、重试和事务所有权保留。
   `LimitOffset` 只是 SQL filter，仍需在 API 边界验证页大小；不引入重复 UoW。

对象存储 UUID 不应随数据库实体 PK 一起切换。现有 `object_key` 取 UUID 前四位做
目录分片，本次连续生成的 256 个 UUIDv7 只有 1 个前缀，uuid4 有多种前缀。
UUIDv7 的时间前缀会集中现有布局；对象与 durable workflow 的身份策略应分别处理。

## 验证范围与来源

Python 3.14.3、SQLAlchemy 2.0.52、Advanced Alchemy 1.11.0：SQLite 实际执行，
PostgreSQL 只编译 SQL。没有可用 PG 服务或容器工具，运行时、迁移与并发结论仍待
项目既有 PostgreSQL gate 验证。未测吞吐、索引大小、深 offset 延迟或生产数据迁移。

Chromium 实际走完四个引导场景、重置和 390px 移动布局，未出现页面错误或横向溢出。
Ruff 与全项目 mypy 检查通过；遵照 prototype skill 未新增测试套件。

参考：[AA 1.11.0 源码](https://github.com/litestar-org/advanced-alchemy/tree/v1.11.0)、
[PyPI](https://pypi.org/project/advanced-alchemy/1.11.0/)、
仓库 `docs/adr/0006-async-runtime-and-persistence.md`、
`docs/architecture/orm-ownership.md` 与当前 Access/目录/Annotations 实现。
