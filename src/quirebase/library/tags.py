from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select

from quirebase.access.items import can_edit_item, visible_items_query
from quirebase.core.errors import (
    DomainError,
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.library.audit import record_audit_event
from quirebase.models import Item, ItemTag, Tag, User
from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TagConflict(DomainError):
    pass


def normalize_tag_name(name: str) -> str:
    normalized = " ".join(name.split())
    if not normalized or len(normalized) > 120:
        raise ValidationFailure("tag must contain 1 to 120 characters")
    return normalized


def add_tag_to_item(db: Session, user: User, item_id: str, name: str) -> ItemTag:
    if not can_edit_item(db, user, item_id):
        raise ResourceUnavailable("item not found or cannot be edited")
    normalized = normalize_tag_name(name)
    tag = db.scalar(select(Tag).where(Tag.name == normalized))
    if tag is None:
        tag = Tag(name=normalized, created_by=user.id)
        db.add(tag)
        db.flush()
    assignment = db.get(ItemTag, (item_id, tag.id))
    if assignment is None:
        assignment = ItemTag(item_id=item_id, tag_id=tag.id)
        db.add(assignment)
        db.flush()
        search_index(db).index_item(db, item_id)
        record_audit_event(db, user.id, "tag.add", "item", item_id)
        db.commit()
    return assignment


def remove_tag_from_item(db: Session, user: User, item_id: str, tag_id: str) -> None:
    if not can_edit_item(db, user, item_id):
        raise ResourceUnavailable("item not found or cannot be edited")
    assignment = db.get(ItemTag, (item_id, tag_id))
    if assignment:
        db.delete(assignment)
        db.flush()
        search_index(db).index_item(db, item_id)
        db.commit()


def rename_tag(db: Session, user: User, tag_id: str, name: str) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None or (tag.created_by != user.id and user.role != "administrator"):
        raise ResourceUnavailable("tag not found or cannot be managed")
    normalized = normalize_tag_name(name)
    if db.scalar(select(Tag.id).where(Tag.name == normalized, Tag.id != tag.id)):
        raise TagConflict("tag name already exists")
    tag.name = normalized
    item_ids = list(db.scalars(select(ItemTag.item_id).where(ItemTag.tag_id == tag.id)).all())
    for item_id in item_ids:
        search_index(db).index_item(db, item_id)
    record_audit_event(db, user.id, "tag.rename", "tag", tag.id)
    db.commit()
    return tag


def delete_tag(db: Session, user: User, tag_id: str) -> None:
    tag = db.get(Tag, tag_id)
    if tag is None or (tag.created_by != user.id and user.role != "administrator"):
        raise ResourceUnavailable("tag not found or cannot be managed")
    item_ids = list(db.scalars(select(ItemTag.item_id).where(ItemTag.tag_id == tag.id)).all())
    db.delete(tag)
    db.flush()
    for item_id in item_ids:
        search_index(db).index_item(db, item_id)
    record_audit_event(db, user.id, "tag.delete", "tag", tag_id)
    db.commit()


def list_accessible_tags_with_counts(db: Session, user: User) -> list[tuple[Tag, int]]:
    accessible_ids = visible_items_query(user).with_only_columns(Item.id).subquery()
    rows = db.execute(
        select(Tag, func.count(ItemTag.item_id))
        .outerjoin(
            ItemTag,
            and_(ItemTag.tag_id == Tag.id, ItemTag.item_id.in_(select(accessible_ids.c.id))),
        )
        .group_by(Tag.id)
        .having(func.count(ItemTag.item_id) > 0)
        .order_by(Tag.name)
    ).all()
    return [(row[0], row[1]) for row in rows]
