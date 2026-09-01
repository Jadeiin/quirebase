from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ProjectWorkspaceMember:
    user: User
    role: ProjectRole


@dataclass(frozen=True)
class ProjectWorkspace:
    project: Project
    membership: ProjectMember
    members: tuple[ProjectWorkspaceMember, ...]
    items: tuple[Item, ...]


async def create_project(db: AsyncSession, user: User, name: str) -> Project:
    normalized = name.strip()
    if not normalized:
        raise ValidationFailure("project name is required")
    project = Project(name=normalized, created_by=user.id)
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.owner))
    record_event(db, user.id, "project.create", "project", project.id)
    await db.commit()
    return project


async def list_user_projects(db: AsyncSession, user: User) -> list[tuple[Project, str, int]]:
    rows = (
        await db.execute(
            select(Project, ProjectMember.role, func.count(ProjectItem.item_id))
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .outerjoin(ProjectItem, ProjectItem.project_id == Project.id)
            .where(ProjectMember.user_id == user.id)
            .group_by(Project.id, ProjectMember.role)
            .order_by(Project.name)
        )
    ).all()
    return [(row[0], row[1], row[2]) for row in rows]


async def open_project_workspace(db: AsyncSession, user: User, project_id: str) -> ProjectWorkspace:
    membership = await require_project_member(db, user, project_id)
    project = await db.get(Project, project_id)
    if project is None:
        raise ResourceNotFound("project not found")
    members_rows = (
        await db.execute(
            select(User, ProjectMember.role)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project_id)
            .order_by(User.username)
        )
    ).all()
    members = tuple(ProjectWorkspaceMember(user=row[0], role=row[1]) for row in members_rows)
    items = tuple(
        (
            await db.scalars(
                select(Item)
                .join(ProjectItem, ProjectItem.item_id == Item.id)
                .where(ProjectItem.project_id == project_id)
                .order_by(Item.updated_at.desc())
            )
        ).all()
    )
    return ProjectWorkspace(
        project=project,
        membership=membership,
        members=members,
        items=items,
    )


async def add_item_to_project(db: AsyncSession, user: User, project_id: str, item_id: str) -> None:
    item = await db.get(Item, item_id)
    membership = await project_member(db, user, project_id)
    if (
        item is None
        or not await can_read_item(db, user, item_id)
        or membership is None
        or membership.role not in (ProjectRole.owner, ProjectRole.editor)
    ):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    if await db.get(ProjectItem, (project_id, item_id)) is None:
        db.add(ProjectItem(project_id=project_id, item_id=item_id))
        await db.flush()
        await search_index(db).index_item(db, item_id)
        record_event(
            db,
            user.id,
            "project.item.add",
            "item",
            item_id,
            detail={"project_id": project_id},
        )
        await db.commit()


async def remove_item_from_project(
    db: AsyncSession, user: User, project_id: str, item_id: str
) -> None:
    membership = await project_member(db, user, project_id)
    assignment = await db.get(ProjectItem, (project_id, item_id))
    if (
        assignment is None
        or not await can_read_item(db, user, item_id)
        or membership is None
        or membership.role not in (ProjectRole.owner, ProjectRole.editor)
    ):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    await db.delete(assignment)
    await db.flush()
    await search_index(db).index_item(db, item_id)
    record_event(
        db,
        user.id,
        "project.item.remove",
        "item",
        item_id,
        detail={"project_id": project_id},
    )
    await db.commit()
