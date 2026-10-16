"""Independent SQL builders and filtered reads over the caller's Session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from advanced_alchemy.filters import LimitOffset
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Insert as PostgreSQLInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import Insert as SQLiteInsert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

if TYPE_CHECKING:
    from collections.abc import Callable

    from advanced_alchemy.base import ModelProtocol
    from advanced_alchemy.filters import StatementFilter
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import DeclarativeBase


def conflict_insert(
    session: AsyncSession, model: type[DeclarativeBase]
) -> PostgreSQLInsert | SQLiteInsert:
    """Build a native conflict-capable INSERT for the supported databases."""
    builders: dict[str, Callable[[type[DeclarativeBase]], PostgreSQLInsert | SQLiteInsert]] = {
        "postgresql": pg_insert,
        "sqlite": sqlite_insert,
    }
    return builders[session.get_bind().dialect.name](model)


async def select_page[ModelT: ModelProtocol](
    db: AsyncSession,
    query: Select[tuple[ModelT]],
    model: type[ModelT],
    *filters: StatementFilter,
) -> tuple[list[ModelT], int]:
    """Count the filtered query independently so empty pages retain their total."""
    for filter_ in filters:
        if not isinstance(filter_, LimitOffset):
            query = filter_.append_to_statement(query, model)
    total = (
        await db.execute(select(func.count()).select_from(query.order_by(None).subquery()))
    ).scalar_one()
    for filter_ in filters:
        if isinstance(filter_, LimitOffset):
            query = filter_.append_to_statement(query, model)
    return list(await db.scalars(query)), total
