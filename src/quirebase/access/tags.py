from __future__ import annotations

from sqlalchemy import Select, select

from quirebase.models import Tag


def visible_tags_query(workspace_id: str) -> Select[tuple[Tag]]:
    return select(Tag).where(Tag.workspace_id == workspace_id)
