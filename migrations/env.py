import asyncio
from logging.config import fileConfig

from alembic import context

import quirebase.models  # ruff: ignore[unused-import]
from quirebase.core.config import get_settings
from quirebase.core.database import Base, make_async_engine

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata

VERSION_TABLE = "alembic_version"
VERSION_NUM_TYPE = "VARCHAR(255)"


def ensure_version_table(connection) -> None:
    """Widen version_num before migrations so revision identifiers may exceed 32 characters.

    Alembic creates this table as VARCHAR(32), which PostgreSQL enforces and SQLite ignores.
    Widening an existing table keeps databases stamped before a longer revision upgradable.
    """
    if connection.dialect.name == "sqlite":
        return
    connection.exec_driver_sql(
        f"CREATE TABLE IF NOT EXISTS {VERSION_TABLE} ("
        f"version_num {VERSION_NUM_TYPE} NOT NULL, "
        f"CONSTRAINT {VERSION_TABLE}_pkc PRIMARY KEY (version_num))"
    )
    connection.exec_driver_sql(
        f"ALTER TABLE {VERSION_TABLE} ALTER COLUMN version_num TYPE {VERSION_NUM_TYPE}"
    )
    connection.commit()


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    ensure_version_table(connection)
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = make_async_engine(config.get_main_option("sqlalchemy.url"))
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


run_migrations_offline() if context.is_offline_mode() else asyncio.run(run_migrations_online())
