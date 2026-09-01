from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.selectable import SelectBase


class SearchIndex(Protocol):
    async def index_item(self, db: AsyncSession, item_id: str) -> None: ...

    async def remove_item(self, db: AsyncSession, item_id: str) -> None: ...

    async def search(self, db: AsyncSession, query: str, limit: int = 200) -> list[str]: ...

    async def matching_item_ids(self, db: AsyncSession, query: str) -> SelectBase: ...
