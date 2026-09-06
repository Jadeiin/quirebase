from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from quirebase.access.projects import project_member
from quirebase.audit import record_event
from quirebase.core.errors import PermissionDenied, ResourceUnavailable, ValidationFailure
from quirebase.models import (
    Project,
    ProjectItem,
    ProjectMember,
    ProjectRole,
    ProjectState,
    ProjectVisibility,
    User,
)
from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def validate_project_state(value: ProjectState | str) -> ProjectState:
    try:
        return ProjectState(value)
    except ValueError as error:
        raise ValidationFailure("invalid project state") from error


async def rename_project(db: AsyncSession, user: User, project_id: str, name: str) -> Project:
    member = await project_member(db, user, project_id)
    project = await db.get(Project, project_id)
    if project is None or (
        (member is None or member.role != ProjectRole.owner) and user.role != "administrator"
    ):
        raise ResourceUnavailable("project not found or owner role required")
    normalized = name.strip()
    if not normalized:
        raise ValidationFailure("project name is required")
    if len(normalized) > 240:
        raise ValidationFailure("project name is too long")
    old_name = project.name
    project.name = normalized
    item_ids = list(
        await db.scalars(select(ProjectItem.item_id).where(ProjectItem.project_id == project_id))
    )
    await db.flush()
    index = search_index(db)
    for item_id in item_ids:
        await index.index_item(db, item_id)
    record_event(
        db,
        user.id,
        "project.rename",
        "project",
        project.id,
        detail={"old_name": old_name, "name": normalized},
    )
    await db.commit()
    return project


async def update_project_description(
    db: AsyncSession, user: User, project_id: str, description: str
) -> Project:
    member = await project_member(db, user, project_id)
    project = await db.get(Project, project_id)
    if project is None or member is None or member.role != ProjectRole.owner:
        raise ResourceUnavailable("project not found or owner role required")
    normalized = description.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > 2000:
        raise ValidationFailure("project description is too long")
    project.description = normalized
    record_event(db, user.id, "project.description.update", "project", project.id)
    await db.commit()
    return project


async def delete_project(db: AsyncSession, user: User, project_id: str, confirmation: str) -> None:
    project = await db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    member = await project_member(db, user, project_id)
    if project is None or (
        user.role != "administrator" and (member is None or member.role != ProjectRole.owner)
    ):
        raise ResourceUnavailable("project not found or owner role required")
    if confirmation.strip() != project.name:
        raise ValidationFailure("project name confirmation does not match")
    item_ids = list(
        await db.scalars(select(ProjectItem.item_id).where(ProjectItem.project_id == project_id))
    )
    record_event(
        db,
        user.id,
        "project.delete",
        "project",
        project.id,
        detail={"name": project.name, "state": project.state.value},
    )
    # Explicitly remove project-owned rows so deletion is deterministic on
    # SQLite deployments where foreign-key cascades may be disabled.
    await db.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id))
    await db.execute(delete(ProjectItem).where(ProjectItem.project_id == project_id))
    await db.delete(project)
    await db.flush()
    index = search_index(db)
    for item_id in item_ids:
        await index.index_item(db, item_id)
    await db.commit()


async def transfer_project_ownership(
    db: AsyncSession, user: User, project_id: str, target_user_id: str
) -> None:
    actor = await project_member(db, user, project_id)
    target = await db.get(ProjectMember, (project_id, target_user_id))
    if actor is None or actor.role != ProjectRole.owner or target is None:
        raise ResourceUnavailable("project or target member not found")
    if target.user_id == user.id:
        raise ValidationFailure("target must be another member")
    target_user = await db.get(User, target.user_id)
    if target_user is None or not target_user.active:
        raise ValidationFailure("target user must be active")
    actor.role = ProjectRole.editor
    target.role = ProjectRole.owner
    record_event(
        db,
        user.id,
        "project.ownership.transfer",
        "project",
        project_id,
        detail={"from_user_id": user.id, "to_user_id": target_user_id},
    )
    await db.commit()


async def leave_project(db: AsyncSession, user: User, project_id: str) -> None:
    # Serialize lifecycle changes for this Project.  The conditional owner
    # deletion below also protects backends (such as SQLite) that ignore
    # ``FOR UPDATE``.
    project = await db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    member = await db.get(ProjectMember, (project_id, user.id))
    if project is None or member is None:
        raise ResourceUnavailable("project membership required")
    if member.role == ProjectRole.owner:
        owner_count = await db.scalar(
            select(func.count())
            .select_from(ProjectMember)
            .where(ProjectMember.project_id == project_id, ProjectMember.role == ProjectRole.owner)
        )
        if (owner_count or 0) <= 1:
            raise PermissionDenied("transfer ownership before leaving")
        # Re-check the count as part of the DELETE predicate so two
        # concurrent last-owner departures cannot both succeed.
        owner_count_subquery = (
            select(func.count())
            .select_from(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.role == ProjectRole.owner,
            )
            .scalar_subquery()
        )
        result = await db.execute(
            delete(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user.id,
                ProjectMember.role == ProjectRole.owner,
                owner_count_subquery > 1,
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            raise PermissionDenied("transfer ownership before leaving")
    else:
        await db.delete(member)
    record_event(db, user.id, "project.member.leave", "project", project_id)
    await db.commit()


async def set_project_state(
    db: AsyncSession, user: User, project_id: str, state: ProjectState
) -> Project:
    state = validate_project_state(state)
    member = await project_member(db, user, project_id)
    project = await db.get(Project, project_id)
    if project is None or (
        (member is None or member.role != ProjectRole.owner) and user.role != "administrator"
    ):
        raise ResourceUnavailable("project not found or owner role required")
    project.state = state
    record_event(db, user.id, f"project.{state.value}", "project", project_id)
    await db.commit()
    return project


async def set_project_visibility(
    db: AsyncSession, user: User, project_id: str, visibility: ProjectVisibility | str
) -> Project:
    try:
        visibility = ProjectVisibility(visibility)
    except ValueError as error:
        raise ValidationFailure("invalid project visibility") from error
    member = await project_member(db, user, project_id)
    project = await db.get(Project, project_id)
    if project is None or (
        (member is None or member.role != ProjectRole.owner) and user.role != "administrator"
    ):
        raise ResourceUnavailable("project not found or owner role required")
    project.visibility = visibility
    record_event(
        db,
        user.id,
        "project.visibility.set",
        "project",
        project_id,
        detail={"visibility": project.visibility.value},
    )
    await db.commit()
    return project
