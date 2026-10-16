from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, select

from quirebase.models import Tag

if TYPE_CHECKING:
    from uuid import UUID


def visible_tags_query(workspace_id: UUID) -> Select[tuple[Tag]]:
    return select(Tag).where(Tag.workspace_id == workspace_id)
