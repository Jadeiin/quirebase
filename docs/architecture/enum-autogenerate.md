# 非原生 Enum 的 Alembic 自动生成

核对日期：2026-10-10。研究对象是 Quirebase 的
`Enum(StrEnum, native_enum=False, create_constraint=True, name=...)`，同时支持 SQLite
和 PostgreSQL；问题出现时使用 Advanced Alchemy 1.11.0、Alembic 1.19.1。

## 结论

无需引入 `alembic-autogenerate-enums` 或 `alembic-postgresql-enum`。二者处理的是
PostgreSQL 原生 ENUM 的生命周期，不能修复本项目两种数据库上的 VARCHAR + CHECK
比较问题，而且官方接入方式都需要在 `env.py` 导入插件。
更小的方案是按本轮要求，将已有 Alembic 升级到当前最新版 **1.20.0**，采用其
默认比较配置，再移除本地 Enum 专用过滤逻辑。相关修复从 1.19.2 起提供，
该补丁已于 2026-09-04 发布，既关闭默认 CHECK 比较，又修复了
显式开启比较时遗漏 type-bound CHECK 的问题。
来源：[插件一说明][auto-pypi]、[插件二源码][pg-declared]、[插件二接入说明][pg-readme]、
[Alembic 1.19.2 发布记录][release]、[1.20.0 发布记录][latest-release]、
[官方 changelog][changelog]、[1.20.0 固定版本文档][docs-1200]。

## 数据库表示与插件范围

SQLAlchemy `Enum` 可以接收 Python 枚举类，`values_callable` 决定持久化成员的
`value`。当 `native_enum=False` 时，所有数据库均使用 VARCHAR；
`create_constraint=True` 再为它生成 CHECK。因此，即使连接 PostgreSQL，本项目
也没有创建可由 `ALTER TYPE` 管理的原生 ENUM 对象。
来源：[SQLAlchemy Enum 文档][sql-enum]。

| 候选 | 已核实版本 | 官方处理范围 | 本项目适用性 |
| --- | --- | --- | --- |
| `alembic-autogenerate-enums` | 0.1.2 | 查询 `pg_catalog.pg_type` / `pg_enum`，生成 `sync_enum_values` 操作；需在 `env.py` 导入 | 不比较 CHECK；源码没有 SQLite 方言保护，直接查询 PostgreSQL 系统目录。[说明][auto-pypi]、[发布源码 wheel][auto-wheel] |
| `alembic-postgresql-enum` | 1.10.0 | 创建、修改、删除 PostgreSQL 原生 ENUM；需在 `env.py` 导入 | `column_type_is_enum()` 对 SQLAlchemy Enum 直接返回 `native_enum`，排除本项目的非原生 Enum；非 PostgreSQL 方言默认直接跳过。[版本][pg-pypi]、[类型筛选源码][pg-declared]、[方言筛选源码][pg-dispatch]、[接入说明][pg-readme] |

为使用这些插件而改为原生 PostgreSQL ENUM，会引入另一套方言专属类型生命周期；
SQLite 的 CHECK 比较仍需单独处理。它们不能减少当前问题的维护范围。
该判断依据上述 SQLAlchemy 表示规则和插件类型、方言筛选源码。

## Alembic 1.19.1 的误判与官方修复

1.19.1 默认启用按名称比较 CHECK 的插件，但 metadata CHECK 收集函数排除
`_type_bound` 约束。SQLAlchemy Enum 生成的 CHECK 属于这一类，而数据库反射得到
的同名 CHECK 被当作普通约束，结果被误判为应删除。
来源：[1.19.1 metadata 收集源码][compat-191]、[1.19.2 对应修复说明][changelog]。

1.19.2 将该插件移为默认关闭的 `alembic.ext.checkconstraint_byname`，
metadata 收集也改为包含 type-bound CHECK；1.20.0 延续这两项行为。因此有以下区别：

| 1.20.0 配置 | 既有表的 CHECK 比较 | 非原生 Enum 值变更 |
| --- | --- | --- |
| 默认配置 | 不自动检测 CHECK 的添加、删除和表达式修改，无需增加 `env.py` 配置 | 不承诺生成枚举值升级操作 |
| 显式启用官方 CHECK 插件 | 按名称检测添加、删除；命名的 Enum CHECK 可正常匹配 | 同名 CHECK 的表达式变化仍被视为相同；只改变枚举值、而不改变 VARCHAR 长度时，不能据此生成升级操作 |

来源：[1.20.0 固定版本文档][docs-1200]、[修复后的 CHECK 收集源码][compat-192]。
显式启用需要在 `context.configure()` 中增加
`autogenerate_plugins=["alembic.autogenerate.*", "alembic.ext.checkconstraint_byname"]`，
因而仍然会改动 `env.py`；本轮自动重建初始 schema 无需该功能。
来源：[官方配置示例及限制][check-docs]。

默认不比较既有表的 CHECK，不影响新建表时通过
`Enum(..., create_constraint=True)` 生成完整枚举 CHECK；初始 schema 的创建与
既有约束差异检测是两个步骤。后续新增、删除枚举成员时仍须审核生成结果，不能将
无 schema diff 当作数据库已接受新值的证明。Alembic 官方明确说明，反射到的
CHAR/VARCHAR + CHECK 无法普遍推断回 SQLAlchemy Enum。
来源：[Enum 创建约束说明][sql-enum]、[Alembic 非原生 Enum 检测边界][detect-docs]、
[CHECK 仅按名称比较的限制][check-docs]。

本记录核实了官方文档、固定版本源码及发布文件，未安装或执行两款外部插件。
实际升级到 1.20.0 后，SQLite/PostgreSQL 的新库 `init-db`、`doctor`、schema 与
metadata 对照、升级降级及无差异 autogenerate 检查均通过；原始 SQL 写入非法枚举值
会被数据库 CHECK 拒绝。SQLite 最小实验还确认：默认配置和官方 CHECK opt-in 对
未变更 Enum 均无差异；opt-in 可检测新增命名业务 CHECK，但不检测同名 Enum CHECK
中的成员变化。

[sql-enum]: https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.Enum
[auto-pypi]: https://pypi.org/project/alembic-autogenerate-enums/0.1.2/
[auto-wheel]: https://files.pythonhosted.org/packages/e9/11/5b63dac59e3761ca021359141ab0fab50e4cbca3ba6da90a7c7d2847328c/alembic_autogenerate_enums-0.1.2-py3-none-any.whl
[pg-pypi]: https://pypi.org/project/alembic-postgresql-enum/1.10.0/
[pg-readme]: https://github.com/Pogchamp-company/alembic-postgresql-enum/blob/v1.10.0/README.md#usage
[pg-declared]: https://github.com/Pogchamp-company/alembic-postgresql-enum/blob/v1.10.0/alembic_postgresql_enum/get_enum_data/declared_enums.py
[pg-dispatch]: https://github.com/Pogchamp-company/alembic-postgresql-enum/blob/v1.10.0/alembic_postgresql_enum/compare_dispatch.py
[release]: https://pypi.org/pypi/alembic/1.19.2/json
[latest-release]: https://pypi.org/pypi/alembic/1.20.0/json
[changelog]: https://github.com/sqlalchemy/alembic/blob/rel_1_19_2/docs/build/changelog.rst
[compat-191]: https://github.com/sqlalchemy/alembic/blob/rel_1_19_1/alembic/util/sqla_compat.py
[compat-192]: https://github.com/sqlalchemy/alembic/blob/rel_1_19_2/alembic/util/sqla_compat.py
[docs-1200]: https://github.com/sqlalchemy/alembic/blob/rel_1_20_0/docs/build/autogenerate.rst
[check-docs]: https://alembic.sqlalchemy.org/en/latest/autogenerate.html#detecting-check-constraints
[detect-docs]: https://alembic.sqlalchemy.org/en/latest/autogenerate.html#what-does-autogenerate-detect-and-what-does-it-not-detect
