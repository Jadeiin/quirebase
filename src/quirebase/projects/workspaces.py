from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from quirebase.access.items import can_read_item
from quirebase.access.projects import project_member, require_project_member
from quirebase.audit import record_event
from quirebase.core.errors import (
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.models import Item, Project, ProjectItem, ProjectMember, ProjectRole, User
from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def create_project(db: Session, user: User, name: str) -> Project:
    normalized = name.strip()
    if not normalized:
        raise ValidationFailure("project name is required")
    project = Project(name=normalized, created_by=user.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.owner))
    record_event(db, user.id, "project.create", "project", project.id)
    db.commit()
    return project


def list_user_projects(db: Session, user: User) -> list[tuple[Project, str, int]]:
    rows = db.execute(
        select(Project, ProjectMember.role, func.count(ProjectItem.item_id))
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .outerjoin(ProjectItem, ProjectItem.project_id == Project.id)
        .where(ProjectMember.user_id == user.id)
        .group_by(Project.id, ProjectMember.role)
        .order_by(Project.name)
    ).all()
    return [(row[0], row[1], row[2]) for row in rows]


def get_project_workspace_data(db: Session, user: User, project_id: str) -> dict[str, Any]:
    membership = require_project_member(db, user, project_id)
    project = db.get(Project, project_id)
    if project is None:
        raise ResourceNotFound("project not found")
    members_rows = db.execute(
        select(User, ProjectMember.role)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.username)
    ).all()
    members = [(row[0], row[1]) for row in members_rows]
    items = list(
        db.scalars(
            select(Item)
            .join(ProjectItem, ProjectItem.item_id == Item.id)
            .where(ProjectItem.project_id == project_id)
            .order_by(Item.updated_at.desc())
        ).all()
    )
    return {
        "project": project,
        "membership": membership,
        "members": members,
        "items": items,
    }


def add_item_to_project(db: Session, user: User, project_id: str, item_id: str) -> None:
    item = db.get(Item, item_id)
    membership = project_member(db, user, project_id)
    if (
        item is None
        or not can_read_item(db, user, item_id)
        or membership is None
        or membership.role not in (ProjectRole.owner, ProjectRole.editor)
    ):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    if db.get(ProjectItem, (project_id, item_id)) is None:
        db.add(ProjectItem(project_id=project_id, item_id=item_id))
        db.flush()
        search_index(db).index_item(db, item_id)
        record_event(
            db,
            user.id,
            "project.item.add",
            "item",
            item_id,
            detail={"project_id": project_id},
        )
        db.commit()


def remove_item_from_project(db: Session, user: User, project_id: str, item_id: str) -> None:
    membership = project_member(db, user, project_id)
    assignment = db.get(ProjectItem, (project_id, item_id))
    if (
        assignment is None
        or not can_read_item(db, user, item_id)
        or membership is None
        or membership.role not in (ProjectRole.owner, ProjectRole.editor)
    ):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    db.delete(assignment)
    db.flush()
    search_index(db).index_item(db, item_id)
    record_event(
        db,
        user.id,
        "project.item.remove",
        "item",
        item_id,
        detail={"project_id": project_id},
    )
    db.commit()
