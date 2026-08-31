from __future__ import annotations

from typing import TYPE_CHECKING

from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def propagate_file_revision_change(
    db: Session, item_id: str, *, owner_id: str | None = None
) -> None:
    """Refresh Item derivatives after its File Revision collection changes."""
    from quirebase.library import request_item_tag_recommendation

    search_index(db).index_item(db, item_id)
    request_item_tag_recommendation(db, item_id, owner_id=owner_id)
