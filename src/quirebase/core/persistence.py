"""Advanced Alchemy configuration for the caller's existing transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import (
    ModelT,
    SQLAlchemyAsyncRepositoryReadService,
    SQLAlchemyAsyncRepositoryService,
)
from sqlalchemy.dialects.postgresql import Insert as PostgreSQLInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import Insert as SQLiteInsert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session

_SESSION_OPTIONS = {
    "auto_commit": False,
    "auto_refresh": False,
    "auto_expunge": False,
    "wrap_exceptions": False,
    "count_with_window_function": False,
}


def conflict_insert(
    session: AsyncSession | async_scoped_session[AsyncSession], model: type[ModelT]
) -> PostgreSQLInsert | SQLiteInsert:
    """Build a native conflict-capable INSERT for the supported databases."""
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return pg_insert(model)
    if dialect == "sqlite":
        return sqlite_insert(model)
    raise ValueError(f"unsupported persistence dialect: {dialect}")


class Repository(SQLAlchemyAsyncRepository[ModelT]):
    def __init__(self, *, session: AsyncSession, **kwargs: Any) -> None:
        super().__init__(session=session, **(_SESSION_OPTIONS | kwargs))


class ReadService(SQLAlchemyAsyncRepositoryReadService[ModelT, SQLAlchemyAsyncRepository[ModelT]]):
    def __init__(self, session: AsyncSession, **kwargs: Any) -> None:
        super().__init__(session=session, **(_SESSION_OPTIONS | kwargs))


class Service(SQLAlchemyAsyncRepositoryService[ModelT, SQLAlchemyAsyncRepository[ModelT]]):
    def __init__(self, session: AsyncSession, **kwargs: Any) -> None:
        super().__init__(session=session, **(_SESSION_OPTIONS | kwargs))
