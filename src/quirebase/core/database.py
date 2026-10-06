from __future__ import annotations

from typing import TYPE_CHECKING, cast

from advanced_alchemy.base import DefaultBase, UUIDv7AuditBase, UUIDv7Base
from advanced_alchemy.config import AsyncSessionConfig, SQLAlchemyAsyncConfig
from advanced_alchemy.types import GUID
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles

from quirebase.core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@compiles(GUID, "sqlite")
def _sqlite_guid_storage(_type, _compiler, **_kwargs) -> str:
    # BINARY has NUMERIC affinity on SQLite and reflects as NUMERIC(16).
    # BLOB stores the same UUID bytes and keeps Alembic roundtrips stable.
    return "BLOB"


class Base(DefaultBase):
    __abstract__ = True
    __bind_key__ = "quirebase"


class EntityBase(UUIDv7AuditBase):
    __abstract__ = True
    __bind_key__ = "quirebase"


class IdentityBase(UUIDv7Base):
    __abstract__ = True
    __bind_key__ = "quirebase"


def _libpq_url(database_url: str) -> str:
    """Return a URL that libpq accepts, rejecting SQLAlchemy driver spellings.

    The application, pg_dump and pg_restore share one connection URL, which keeps the
    supported configuration to a single spelling. Driver-suffixed forms such as
    ``postgresql+psycopg://``, ``postgresql+psycopg2://`` or ``postgresql+asyncpg://`` are
    configuration errors instead of being rewritten.
    """
    if database_url.startswith(("postgres://", "postgresql://")):
        return database_url
    if database_url.startswith("postgres"):
        scheme = database_url.split("://", 1)[0]
        raise ValueError(
            f"unsupported database URL scheme {scheme!r}; use a libpq URL such as "
            "postgresql://user:password@host/database"
        )
    return database_url


def async_database_url(url: str | None = None) -> str:
    database_url = _libpq_url(url or get_settings().database_url)
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    if database_url.startswith("sqlite+aiosqlite:///"):
        return database_url
    if database_url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + database_url.removeprefix("sqlite:///")
    return database_url


def is_sqlite_database_url(url: str | None = None) -> bool:
    database_url = url or get_settings().database_url
    return database_url.startswith(("sqlite:///", "sqlite+aiosqlite:///"))


def make_async_engine(url: str | None = None) -> AsyncEngine:
    database_url = async_database_url(url)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def configure_sqlite(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


engine = make_async_engine()
database_config = SQLAlchemyAsyncConfig(
    engine_instance=engine,
    metadata=Base.metadata,
    session_config=AsyncSessionConfig(expire_on_commit=False),
    enable_file_object_listener=False,
    # AuditColumns supplies onupdate for ORM and SQL DML; keep explicit overrides.
    enable_touch_updated_timestamp_listener=False,
)
AsyncSessionLocal = cast("async_sessionmaker[AsyncSession]", database_config.create_session_maker())


async def get_db() -> AsyncIterator[AsyncSession]:
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()
