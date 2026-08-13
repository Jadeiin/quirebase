from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from .models import FileRevision, Item, PdfAnnotation, ProjectItem, ProjectMember, SystemRole, User


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


def require_revision(db: Session, user: User, revision_id: str) -> FileRevision:
    revision = db.get(FileRevision, revision_id)
    if revision is None or not can_read_item(db, user, revision.item_id):
        raise HTTPException(status_code=404, detail="PDF revision not found")
    return revision


def project_member(db: Session, user: User, project_id: str | None) -> ProjectMember | None:
    if project_id is None:
        return None
    return db.get(ProjectMember, (project_id, user.id))


def can_edit_annotation(db: Session, user: User, annotation: PdfAnnotation) -> bool:
    if annotation.author_id == user.id or user.role == SystemRole.administrator.value:
        return True
    if annotation.scope == "project" and annotation.project_id:
        member = project_member(db, user, annotation.project_id)
        return member is not None and member.role == "owner"
    return False
