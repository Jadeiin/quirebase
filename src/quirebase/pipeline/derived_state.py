from __future__ import annotations

from typing import TYPE_CHECKING

from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def propagate_file_revision_change(
    db: AsyncSession, item_id: str, *, owner_id: str | None = None
) -> None:
    """Refresh Item derivatives after its File Revision collection changes."""
    from quirebase.library import request_item_tag_recommendation

    await search_index(db).index_item(db, item_id)
    await request_item_tag_recommendation(db, item_id, owner_id=owner_id)
