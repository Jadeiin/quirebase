from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from alembic import context
from dbos._schemas.datasource_database import DatasourceSchema
from dbos._schemas.system_database import SystemSchema

import quirebase.models  # ruff: ignore[unused-import]
from quirebase.core.database import Base, database_config
from quirebase.core.storage import get_object_store

if TYPE_CHECKING:
    from advanced_alchemy.alembic.commands import AlembicCommandConfig
    from sqlalchemy.engine import Connection

config = cast("AlembicCommandConfig", context.config)
alembic_config = database_config.alembic_config

target_metadata = Base.metadata

# The dialect-specific search projections (FTS5 on SQLite, tsvector tables on PostgreSQL)
# are created by raw SQL in the initial revision and are deliberately absent from
# Base.metadata. Autogenerate would otherwise reflect them, including SQLite's FTS5
# shadow tables, and emit DROP TABLE operations for them.
SEARCH_PROJECTION_TABLES = frozenset({"item_search", "revision_search"})
FTS5_SHADOW_SUFFIXES = (
    "_config",
    "_content",
    "_data",
    "_docsize",
    "_idx",
    "_segdir",
    "_segments",
    "_stat",
)
# Alembic owns business tables; DBOS owns its system and datasource tables.
DBOS_TABLES = frozenset(
    table.name
    for metadata in (SystemSchema.metadata_obj, DatasourceSchema.metadata_obj)
    for table in metadata.tables.values()
) | {"dbos_migrations"}


def _is_search_projection(name: str) -> bool:
    return name in SEARCH_PROJECTION_TABLES or any(
        name == f"{table}{suffix}"
        for table in SEARCH_PROJECTION_TABLES
        for suffix in FTS5_SHADOW_SUFFIXES
    )


def include_object(_object, name, type_, reflected, _compare_to):
    """Keep Search projections and DBOS-owned infrastructure out of business revisions."""
    return not (
        type_ == "table" and reflected and (_is_search_projection(name) or name in DBOS_TABLES)
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=config.db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        version_table=config.version_table_name,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=alembic_config.compare_type,
        render_as_batch=alembic_config.render_as_batch,
        user_module_prefix=alembic_config.user_module_prefix,
        version_table=config.version_table_name,
        include_object=include_object,
    )
    if context.get_context().opts.get("revision_context") is not None:
        # StoredObject's native repr resolves its backend key during autogenerate.
        get_object_store()

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode against the application's async engine."""
    connectable = config.engine

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
