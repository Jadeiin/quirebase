from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, exists, or_, select

from quirebase.core.errors import ResourceNotFound, ResourceUnavailable, ValidationFailure
from quirebase.models import Item, ProjectItem, ProjectMember, SystemRole, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def visible_items_query(user: User) -> Select[tuple[Item]]:
    query = select(Item)
    if user.role == SystemRole.administrator.value:
        return query
    project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    shared_ids = select(ProjectItem.item_id).where(ProjectItem.project_id.in_(project_ids))
    return query.where(or_(Item.created_by == user.id, Item.id.in_(shared_ids)))


def can_read_item(db: Session, user: User, item_id: str) -> bool:
    if user.role == SystemRole.administrator.value:
        return db.get(Item, item_id) is not None
    own = exists().where(Item.id == item_id, Item.created_by == user.id)
    shared = exists().where(
        ProjectItem.item_id == item_id,
        ProjectMember.project_id == ProjectItem.project_id,
        ProjectMember.user_id == user.id,
    )
    return bool(db.scalar(select(or_(own, shared))))


def can_edit_item(db: Session, user: User, item_id: str) -> bool:
    item = db.get(Item, item_id)
    if item is None:
        return False
    if user.role == SystemRole.administrator.value or item.created_by == user.id:
        return True
    editable = exists().where(
        ProjectItem.item_id == item_id,
        ProjectMember.project_id == ProjectItem.project_id,
        ProjectMember.user_id == user.id,
        ProjectMember.role.in_(["owner", "editor"]),
    )
    return bool(db.scalar(select(editable)))


def can_delete_item(db: Session, user: User, item: Item) -> bool:
    if user.role == SystemRole.administrator.value:
        return True
    return item.created_by == user.id


def require_readable_item(db: Session, user: User, item_id: str) -> Item:
    if not can_read_item(db, user, item_id):
        raise ResourceUnavailable("item not found")
    item = db.get(Item, item_id)
    if item is None:
        raise ResourceNotFound("item not found")
    return item


def require_editable_item(db: Session, user: User, item_id: str) -> Item:
    if not can_edit_item(db, user, item_id):
        raise ResourceUnavailable("item not found")
    item = db.get(Item, item_id)
    if item is None:
        raise ResourceNotFound("item not found")
    return item


def require_accessible_items(db: Session, user: User, item_ids: list[str]) -> list[Item]:
    selected = [db.get(Item, item_id) for item_id in dict.fromkeys(item_ids)]
    items = [item for item in selected if item is not None and can_read_item(db, user, item.id)]
    if not items or len(items) != len(selected):
        raise ValidationFailure("select one or more accessible items")
    return items
