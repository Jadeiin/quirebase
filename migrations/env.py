from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic import context

import quirebase.models  # ruff: ignore[unused-import]
from quirebase.core.config import get_settings
from quirebase.core.database import Base, make_async_engine

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The application owns the database URL; alembic.ini only carries a placeholder.
database_url = get_settings().database_url

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


def _is_search_projection(name: str) -> bool:
    return name in SEARCH_PROJECTION_TABLES or any(
        name == f"{table}{suffix}"
        for table in SEARCH_PROJECTION_TABLES
        for suffix in FTS5_SHADOW_SUFFIXES
    )


def include_object(_object, name, type_, reflected, _compare_to):
    """Keep database-only search projections out of autogenerate diffs."""
    return not (type_ == "table" and reflected and _is_search_projection(name))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode against the application's async engine."""
    connectable = make_async_engine(database_url)

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
