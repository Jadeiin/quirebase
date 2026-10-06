"""Advanced Alchemy configuration for the caller's existing transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import (
    ModelT,
    SQLAlchemyAsyncRepositoryReadService,
    SQLAlchemyAsyncRepositoryService,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_SESSION_OPTIONS = {
    "auto_commit": False,
    "auto_refresh": False,
    "auto_expunge": False,
    "wrap_exceptions": False,
    "count_with_window_function": False,
}


class Repository(SQLAlchemyAsyncRepository[ModelT]):
    def __init__(self, *, session: AsyncSession, **kwargs: Any) -> None:
        super().__init__(session=session, **(_SESSION_OPTIONS | kwargs))


class ReadService(SQLAlchemyAsyncRepositoryReadService[ModelT, SQLAlchemyAsyncRepository[ModelT]]):
    def __init__(self, session: AsyncSession, **kwargs: Any) -> None:
        super().__init__(session=session, **(_SESSION_OPTIONS | kwargs))


class Service(SQLAlchemyAsyncRepositoryService[ModelT, SQLAlchemyAsyncRepository[ModelT]]):
    def __init__(self, session: AsyncSession, **kwargs: Any) -> None:
        super().__init__(session=session, **(_SESSION_OPTIONS | kwargs))
