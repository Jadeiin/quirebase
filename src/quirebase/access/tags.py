from __future__ import annotations

from sqlalchemy import Select, exists, or_, select

from quirebase.access.items import visible_items_query
from quirebase.models import Item, ItemTag, SystemRole, Tag, User


def visible_tags_query(user: User) -> Select[tuple[Tag]]:
    query = select(Tag)
    if user.role == SystemRole.administrator.value:
        return query
    accessible_ids = visible_items_query(user).with_only_columns(Item.id).subquery()
    return query.where(
        or_(
            Tag.created_by == user.id,
            exists().where(
                ItemTag.tag_id == Tag.id,
                ItemTag.item_id.in_(select(accessible_ids.c.id)),
            ),
        )
    )
