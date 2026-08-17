from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, delete, func, select

from quirebase.access.items import can_edit_item, can_read_item, visible_items_query
from quirebase.audit import record_event
from quirebase.core.errors import (
    DomainError,
    ResourceUnavailable,
    ValidationFailure,
)
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


def get_or_create_tag(db: Session, user: User, name: str) -> Tag:
    normalized = normalize_tag_name(name)
    tag = db.scalar(select(Tag).where(Tag.name == normalized))
    if tag is None:
        tag = Tag(name=normalized, created_by=user.id)
        db.add(tag)
        db.flush()
    return tag


def add_tag_to_item(db: Session, user: User, item_id: str, name: str) -> ItemTag:
    if not can_edit_item(db, user, item_id):
        raise ResourceUnavailable("item not found or cannot be edited")
    tag = get_or_create_tag(db, user, name)
    assignment = db.get(ItemTag, (item_id, tag.id))
    if assignment is None:
        assignment = ItemTag(item_id=item_id, tag_id=tag.id)
        db.add(assignment)
        db.flush()
        search_index(db).index_item(db, item_id)
        record_event(db, user.id, "tag.add", "item", item_id)
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
    record_event(db, user.id, "tag.rename", "tag", tag.id)
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
    record_event(db, user.id, "tag.delete", "tag", tag_id)
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
        .order_by(Tag.name)
    ).all()
    return [(row[0], row[1]) for row in rows]


def recommend_tags_for_item(db: Session, user: User, item_id: str) -> list[Tag]:
    if not can_read_item(db, user, item_id):
        return []
    item = db.get(Item, item_id)
    if item is None:
        return []
    words = _recommendation_words(item)
    if not words:
        return []
    # Limit word pool
    word_list = list(words)[:500]
    return list(
        db.scalars(select(Tag).where(func.lower(Tag.name).in_(word_list)).order_by(Tag.name)).all()
    )


def _recommendation_words(item: Item) -> set[str]:
    text = f"{item.title or ''} {item.abstract or ''} {item.keywords or ''}"
    return {
        word.lower() for word in re.findall(r"[A-Za-z0-9\u4e00-\u9fa5]+", text) if len(word) > 1
    }


def get_tag_matrix_for_item(db: Session, user: User, item_id: str) -> dict[str, Any]:
    if not can_read_item(db, user, item_id):
        raise ResourceUnavailable("item not found")
    all_tags = list(db.scalars(select(Tag).order_by(Tag.name)).all())
    assigned_ids = set(db.scalars(select(ItemTag.tag_id).where(ItemTag.item_id == item_id)).all())
    item = db.get(Item, item_id)
    word_pool = list(_recommendation_words(item))[:500] if item is not None else []
    recommended_words = set(word_pool)
    recommended_ids = {tag.id for tag in all_tags if tag.name.lower() in recommended_words}

    # Group by first letter A-Z or '#'
    groups_dict: dict[str, list[Tag]] = {}
    for tag in all_tags:
        first_char = tag.name[0].upper() if tag.name else "#"
        if not ("A" <= first_char <= "Z"):
            first_char = "#"
        groups_dict.setdefault(first_char, []).append(tag)

    sorted_letters = sorted(groups_dict.keys(), key=lambda k: (k == "#", k))
    groups = [
        {
            "letter": letter,
            "tags": groups_dict[letter],
            "names": [t.name for t in groups_dict[letter]],
        }
        for letter in sorted_letters
    ]

    return {
        "groups": groups,
        "assigned_ids": assigned_ids,
        "recommended_ids": recommended_ids,
    }


def batch_add_tags_to_item(db: Session, user: User, item_id: str, names: list[str]) -> list[Tag]:
    if not can_edit_item(db, user, item_id):
        raise ResourceUnavailable("item not found or cannot be edited")
    added: list[Tag] = []
    for raw_name in names:
        if not raw_name.strip():
            continue
        tag = get_or_create_tag(db, user, raw_name)
        assignment = db.get(ItemTag, (item_id, tag.id))
        if assignment is None:
            assignment = ItemTag(item_id=item_id, tag_id=tag.id)
            db.add(assignment)
            db.flush()
        added.append(tag)
    search_index(db).index_item(db, item_id)
    record_event(db, user.id, "tag.batch_add", "item", item_id)
    db.commit()
    return added


def set_item_tags(
    db: Session,
    user: User,
    item_id: str,
    tag_ids: list[str],
    new_names: list[str] | None = None,
) -> None:
    if not can_edit_item(db, user, item_id):
        raise ResourceUnavailable("item not found or cannot be edited")
    tag_ids = list(tag_ids)
    for raw_name in new_names or []:
        if raw_name.strip():
            tag = get_or_create_tag(db, user, raw_name)
            if tag.id not in tag_ids:
                tag_ids.append(tag.id)
    db.execute(delete(ItemTag).where(ItemTag.item_id == item_id))
    db.flush()
    valid_ids = set(db.scalars(select(Tag.id).where(Tag.id.in_(tag_ids))).all())
    for tag_id in tag_ids:
        if tag_id in valid_ids:
            db.add(ItemTag(item_id=item_id, tag_id=tag_id))
    db.flush()
    search_index(db).index_item(db, item_id)
    record_event(db, user.id, "tag.set", "item", item_id)
    db.commit()


def merge_tags(db: Session, user: User, source_tag_id: str, target_tag_id: str) -> Tag:
    source_tag = db.get(Tag, source_tag_id)
    target_tag = db.get(Tag, target_tag_id)
    if source_tag is None or target_tag is None:
        raise ResourceUnavailable("tags not found")
    if (
        user.role != "administrator"
        and source_tag.created_by != user.id
        and target_tag.created_by != user.id
    ):
        raise ResourceUnavailable("not authorized to merge these tags")

    # Re-link items from source to target
    source_items = list(
        db.scalars(select(ItemTag.item_id).where(ItemTag.tag_id == source_tag.id)).all()
    )
    already_linked = set(
        db.scalars(
            select(ItemTag.item_id).where(
                ItemTag.tag_id == target_tag.id, ItemTag.item_id.in_(source_items)
            )
        ).all()
    )
    for item_id in source_items:
        if item_id not in already_linked:
            db.add(ItemTag(item_id=item_id, tag_id=target_tag.id))
    db.execute(delete(ItemTag).where(ItemTag.tag_id == source_tag.id))
    db.delete(source_tag)
    db.flush()

    for item_id in source_items:
        search_index(db).index_item(db, item_id)
    record_event(
        db,
        user.id,
        "tag.merge",
        "tag",
        target_tag.id,
        detail={"merged_from": source_tag.name},
    )
    db.commit()
    return target_tag
