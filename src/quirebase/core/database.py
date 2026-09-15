from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from quirebase.core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class Base(DeclarativeBase):
    pass


_ASYNC_ONLY_QUERY_OPTIONS = frozenset({
    "command_timeout",
    "connection_class",
    "direct_tls",
    "max_cacheable_statement_size",
    "max_cached_statement_lifetime",
    "prepared_statement_cache_size",
    "server_settings",
    "statement_cache_size",
    "timeout",
})

_SSL_MODE_ALIASES = {
    "0": "disable",
    "1": "require",
    "false": "disable",
    "no": "disable",
    "off": "disable",
    "on": "require",
    "true": "require",
    "yes": "require",
}

_SSL_MODES = frozenset({"allow", "disable", "prefer", "require", "verify-ca", "verify-full"})


def _psycopg_compatible_url(database_url: str) -> str:
    """Rewrite asyncpg URL options into the psycopg/libpq spelling.

    asyncpg accepts query options that libpq rejects outright, such as ``ssl=require``,
    so a normalized URL would otherwise fail at engine creation with an opaque error.
    """
    url = make_url(database_url)
    query = dict(url.query)
    ssl_value = query.pop("ssl", None)
    if ssl_value is not None:
        sslmode = _SSL_MODE_ALIASES.get(str(ssl_value).strip().lower(), str(ssl_value).lower())
        if sslmode not in _SSL_MODES:
            supported = ", ".join(sorted(_SSL_MODES))
            raise ValueError(
                f"unsupported asyncpg ssl option {ssl_value!r}; use sslmode with one of: {supported}"
            )
        query["sslmode"] = sslmode
    unsupported = sorted(option for option in query if option in _ASYNC_ONLY_QUERY_OPTIONS)
    if unsupported:
        raise ValueError(
            "the database URL uses asyncpg-only options that psycopg and libpq do not accept: "
            + ", ".join(unsupported)
        )
    return url.set(query=query).render_as_string(hide_password=False)


def async_database_url(url: str | None = None) -> str:
    database_url = url or get_settings().database_url
    if database_url.startswith("sqlite+aiosqlite:///"):
        return database_url
    if database_url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + database_url.removeprefix("sqlite:///")
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    elif database_url.startswith("postgresql+psycopg2://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql+psycopg2://")
    elif database_url.startswith("postgresql+asyncpg://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql+asyncpg://")
    if database_url.startswith("postgresql+psycopg://"):
        return _psycopg_compatible_url(database_url)
    return database_url


def is_sqlite_database_url(url: str | None = None) -> bool:
    database_url = url or get_settings().database_url
    return database_url.startswith(("sqlite:///", "sqlite+aiosqlite:///"))


def libpq_database_url(url: str | None = None) -> str:
    database_url = url or get_settings().database_url
    for prefix in (
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
        "postgresql+asyncpg://",
        "postgres://",
    ):
        if database_url.startswith(prefix):
            database_url = "postgresql://" + database_url.removeprefix(prefix)
            break
    if database_url.startswith("postgresql://"):
        return _psycopg_compatible_url(database_url)
    return database_url


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
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()
