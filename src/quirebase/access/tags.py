from __future__ import annotations

from sqlalchemy import Select, exists, or_, select

from quirebase.access.items import visible_items_query
from quirebase.models import Item, PersonalItemTag, SystemRole, Tag, User


def can_manage_tag(user: User, tag: Tag) -> bool:
    return tag.created_by == user.id or user.role == SystemRole.administrator.value


def visible_tags_query(user: User) -> Select[tuple[Tag]]:
    query = select(Tag)
    if user.role == SystemRole.administrator.value:
        return query.where(Tag.user_id.is_not(None))
    accessible_ids = visible_items_query(user).with_only_columns(Item.id).subquery()
    return query.where(
        or_(
            (Tag.user_id == user.id),
            exists().where(
                PersonalItemTag.tag_id == Tag.id,
                PersonalItemTag.item_id.in_(select(accessible_ids.c.id)),
            ),
        )
    )
