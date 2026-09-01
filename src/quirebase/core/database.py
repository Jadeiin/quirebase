from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import event
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


def async_database_url(url: str | None = None) -> str:
    database_url = url or get_settings().database_url
    if database_url.startswith("sqlite:///") and not database_url.startswith(
        "sqlite+aiosqlite:///"
    ):
        return "sqlite+aiosqlite:///" + database_url.removeprefix("sqlite:///")
    if database_url.startswith(("postgres://", "postgresql://")):
        prefix = "postgres://" if database_url.startswith("postgres://") else "postgresql://"
        return "postgresql+psycopg://" + database_url.removeprefix(prefix)
    if database_url.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql+psycopg2://")
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
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()
