from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from quirebase.access.items import can_read_item
from quirebase.access.projects import require_project_member
from quirebase.audit import record_event
from quirebase.core.errors import (
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.models import (
    Item,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectRole,
    ProjectState,
    ProjectVisibility,
    User,
)
from quirebase.search import enqueue_search_changed

from .write_gate import require_project_write_gate


async def _lock_active_user(db: AsyncSession, user: User) -> User:
    locked = await db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or not locked.active:
        raise ResourceUnavailable("user is not active")
    return locked


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


async def create_project(
    db: AsyncSession,
    user: User,
    name: str,
    visibility: ProjectVisibility | str = ProjectVisibility.private,
    description: str = "",
) -> Project:
    normalized = name.strip()
    if not normalized:
        raise ValidationFailure("project name is required")
    try:
        parsed_visibility = ProjectVisibility(visibility)
    except ValueError as error:
        raise ValidationFailure("invalid project visibility") from error
    normalized_description = description.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized_description) > 2000:
        raise ValidationFailure("project description is too long")
    project = Project(
        name=normalized,
        created_by=user.id,
        visibility=parsed_visibility,
        description=normalized_description,
    )
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


async def list_joinable_projects(db: AsyncSession, user: User) -> list[tuple[Project, int]]:
    rows = await db.execute(
        select(Project, func.count(ProjectItem.item_id))
        .outerjoin(ProjectItem)
        .where(
            Project.visibility == ProjectVisibility.public,
            Project.state == "active",
            ~select(ProjectMember.project_id)
            .where(ProjectMember.project_id == Project.id, ProjectMember.user_id == user.id)
            .exists(),
        )
        .group_by(Project.id)
        .order_by(Project.name)
    )
    return [(row[0], row[1]) for row in rows]


async def join_project(db: AsyncSession, user: User, project_id: str) -> ProjectMember:
    user = await _lock_active_user(db, user)
    await require_project_write_gate(
        db,
        project_id,
        state=ProjectState.active,
        visibility=ProjectVisibility.public,
        message="public project not available",
    )
    existing = await db.get(ProjectMember, (project_id, user.id), populate_existing=True)
    if existing:
        await db.commit()
        return existing
    member = ProjectMember(project_id=project_id, user_id=user.id, role=ProjectRole.viewer)
    db.add(member)
    record_event(db, user.id, "project.member.join", "project", project_id)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent retry may have inserted the same composite key.  The
        # failed transaction must be rolled back before reloading it.
        await db.rollback()
        existing = await db.get(ProjectMember, (project_id, user.id))
        if existing is None:
            raise
        return existing
    return member


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
    user = await _lock_active_user(db, user)
    item = await db.get(Item, item_id)
    if item is None or not await can_read_item(db, user, item_id):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    await require_project_write_gate(
        db,
        project_id,
        state=ProjectState.active,
        message="item or project not accessible or insufficient permissions",
    )
    membership = await db.get(ProjectMember, (project_id, user.id), populate_existing=True)
    if membership is None or membership.role not in (ProjectRole.owner, ProjectRole.editor):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    if await db.get(ProjectItem, (project_id, item_id), populate_existing=True) is None:
        db.add(ProjectItem(project_id=project_id, item_id=item_id))
        await db.flush()
        await db.execute(
            update(Item)
            .where(Item.id == item_id)
            .values(aggregate_sequence=Item.aggregate_sequence + 1)
        )
        await enqueue_search_changed(db, item_id)
        record_event(
            db,
            user.id,
            "project.item.add",
            "item",
            item_id,
            detail={"project_id": project_id},
        )
    await db.commit()


async def add_items_to_project(
    db: AsyncSession, user: User, project_id: str, item_ids: list[str]
) -> tuple[str, ...]:
    """Projects-owned bulk ProjectItem mutation used by Library commands."""

    user = await _lock_active_user(db, user)
    await require_project_write_gate(
        db,
        project_id,
        state=ProjectState.active,
        message="item or project not accessible or insufficient permissions",
    )
    membership = await db.get(ProjectMember, (project_id, user.id), populate_existing=True)
    if membership is None or membership.role not in (ProjectRole.owner, ProjectRole.editor):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    changed: list[str] = []
    for item_id in dict.fromkeys(item_ids):
        item = await db.get(Item, item_id, populate_existing=True)
        state = getattr(item.lifecycle_state, "value", item.lifecycle_state) if item else None
        if item is None or state != "active":
            raise ResourceUnavailable("item or project not accessible or insufficient permissions")
        if await db.get(ProjectItem, (project_id, item_id), populate_existing=True) is None:
            db.add(ProjectItem(project_id=project_id, item_id=item_id))
            await db.execute(
                update(Item)
                .where(Item.id == item_id, Item.lifecycle_state == "active")
                .values(aggregate_sequence=Item.aggregate_sequence + 1)
            )
            await enqueue_search_changed(db, item_id)
            changed.append(item_id)
    return tuple(changed)


async def remove_item_from_project(
    db: AsyncSession, user: User, project_id: str, item_id: str
) -> None:
    user = await _lock_active_user(db, user)
    if not await can_read_item(db, user, item_id):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    await require_project_write_gate(
        db,
        project_id,
        state=ProjectState.active,
        message="item or project not accessible or insufficient permissions",
    )
    membership = await db.get(ProjectMember, (project_id, user.id), populate_existing=True)
    assignment = await db.get(ProjectItem, (project_id, item_id), populate_existing=True)
    if (
        assignment is None
        or membership is None
        or membership.role not in (ProjectRole.owner, ProjectRole.editor)
    ):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    await db.delete(assignment)
    await db.flush()
    await db.execute(
        update(Item)
        .where(Item.id == item_id)
        .values(aggregate_sequence=Item.aggregate_sequence + 1)
    )
    await enqueue_search_changed(db, item_id)
    record_event(
        db,
        user.id,
        "project.item.remove",
        "item",
        item_id,
        detail={"project_id": project_id},
    )
    await db.commit()
