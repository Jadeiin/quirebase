from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from quirebase.audit import record_event
from quirebase.core.errors import PermissionDenied, ResourceUnavailable, ValidationFailure
from quirebase.models import (
    Item,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectRole,
    ProjectSharingMode,
    ProjectState,
    ProjectVisibility,
    User,
)

from ._locking import lock_project_delete, lock_project_root
from .sharing import clone_item_for_project

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def validate_project_state(value: ProjectState | str) -> ProjectState:
    try:
        return ProjectState(value)
    except ValueError as error:
        raise ValidationFailure("invalid project state") from error


async def rename_project(db: AsyncSession, user: User, project_id: str, name: str) -> Project:
    project = await lock_project_root(db, project_id)
    member = await db.get(ProjectMember, (project_id, user.id))
    if (
        project is None
        or project.state is ProjectState.archived
        or (
            user.role != "administrator"
            and (member is None or member.role is not ProjectRole.admin)
        )
    ):
        raise ResourceUnavailable("project not found or project admin role required")
    normalized = name.strip()
    if not normalized:
        raise ValidationFailure("project name is required")
    if len(normalized) > 240:
        raise ValidationFailure("project name is too long")
    old_name = project.name
    project.name = normalized
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


async def update_project_settings(
    db: AsyncSession,
    user: User,
    project_id: str,
    *,
    name: str,
    description: str,
    visibility: ProjectVisibility | str,
    sharing_mode: ProjectSharingMode | str = ProjectSharingMode.live,
) -> Project:
    """Validate and commit the editable Project settings as one operation."""
    normalized_name = name.strip()
    if not normalized_name:
        raise ValidationFailure("project name is required")
    if len(normalized_name) > 240:
        raise ValidationFailure("project name is too long")
    normalized_description = description.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized_description) > 2000:
        raise ValidationFailure("project description is too long")
    try:
        normalized_visibility = ProjectVisibility(visibility)
    except ValueError as error:
        raise ValidationFailure("invalid project visibility") from error
    try:
        normalized_mode = ProjectSharingMode(sharing_mode)
    except ValueError as error:
        raise ValidationFailure("invalid project sharing mode") from error

    project = await lock_project_root(db, project_id)
    member = await db.get(ProjectMember, (project_id, user.id))
    if (
        project is None
        or project.state is ProjectState.archived
        or (
            user.role != "administrator"
            and (member is None or member.role is not ProjectRole.admin)
        )
    ):
        raise ResourceUnavailable("project not found or project admin role required")
    old_values = {
        "name": project.name,
        "description": project.description,
        "visibility": project.visibility.value,
        "sharing_mode": project.sharing_mode.value,
    }
    project.name = normalized_name
    project.description = normalized_description
    project.visibility = normalized_visibility
    if (
        project.sharing_mode is ProjectSharingMode.live
        and normalized_mode is ProjectSharingMode.independent
    ):
        assignments = list(
            (
                await db.scalars(
                    select(ProjectItem)
                    .where(ProjectItem.project_id == project_id)
                    .order_by(ProjectItem.id)
                    .with_for_update()
                )
            ).all()
        )
        for assignment in assignments:
            source = await db.get(Item, assignment.item_id, populate_existing=True)
            if source is None:
                raise ResourceUnavailable("project item source no longer exists")
            if source.owner_id is None:
                continue
            assignment.item_id = (await clone_item_for_project(db, source, user)).id
    project.sharing_mode = normalized_mode
    record_event(
        db,
        user.id,
        "project.settings.update",
        "project",
        project.id,
        detail={
            "old": old_values,
            "new": {
                "name": normalized_name,
                "description": normalized_description,
                "visibility": normalized_visibility.value,
                "sharing_mode": normalized_mode.value,
            },
        },
    )
    await db.commit()
    return project


async def update_project_description(
    db: AsyncSession, user: User, project_id: str, description: str
) -> Project:
    project = await lock_project_root(db, project_id)
    member = await db.get(ProjectMember, (project_id, user.id))
    if (
        project is None
        or project.state is ProjectState.archived
        or (member is None or member.role is not ProjectRole.admin)
    ):
        raise ResourceUnavailable("project not found or project admin role required")
    normalized = description.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > 2000:
        raise ValidationFailure("project description is too long")
    project.description = normalized
    record_event(db, user.id, "project.description.update", "project", project.id)
    await db.commit()
    return project


async def delete_project(db: AsyncSession, user: User, project_id: str, confirmation: str) -> None:
    project = await lock_project_delete(db, project_id)
    member = await db.get(ProjectMember, (project_id, user.id))
    if (
        project is None
        or project.state is ProjectState.archived
        or (
            user.role != "administrator"
            and (member is None or member.role is not ProjectRole.admin)
        )
    ):
        raise ResourceUnavailable("project not found or project admin role required")
    if confirmation.strip() != project.name:
        raise ValidationFailure("project name confirmation does not match")
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
    await db.commit()


async def leave_project(db: AsyncSession, user: User, project_id: str) -> None:
    await lock_project_root(db, project_id)
    project = await db.get(Project, project_id, populate_existing=True)
    member = await db.get(ProjectMember, (project_id, user.id), populate_existing=True)
    if project is None or member is None:
        raise ResourceUnavailable("project membership required")
    if member.role is ProjectRole.admin:
        remaining_admins = await db.scalar(
            select(ProjectMember.user_id)
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.role == ProjectRole.admin,
                ProjectMember.user_id != user.id,
                User.active.is_(True),
            )
            .limit(1)
        )
        if remaining_admins is None:
            raise PermissionDenied("a project must retain an active admin")
    if member.role in (ProjectRole.admin, ProjectRole.editor):
        from .sharing import fork_owned_project_items

        await fork_owned_project_items(db, project_id, user.id, user)
    await db.delete(member)
    record_event(db, user.id, "project.member.leave", "project", project_id)
    await db.commit()


async def set_project_state(
    db: AsyncSession, user: User, project_id: str, state: ProjectState
) -> Project:
    state = validate_project_state(state)
    project = await lock_project_root(db, project_id)
    member = await db.get(ProjectMember, (project_id, user.id))
    if (
        project is None
        or project.state is ProjectState.archived
        or (
            user.role != "administrator"
            and (member is None or member.role is not ProjectRole.admin)
        )
    ):
        raise ResourceUnavailable("project not found or project admin role required")
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
    project = await lock_project_root(db, project_id)
    member = await db.get(ProjectMember, (project_id, user.id))
    if project is None or (
        user.role != "administrator" and (member is None or member.role is not ProjectRole.admin)
    ):
        raise ResourceUnavailable("project not found or project admin role required")
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


async def change_project_sharing_mode(
    db: AsyncSession,
    user: User,
    project_id: str,
    sharing_mode: ProjectSharingMode | str,
) -> Project:
    try:
        mode = ProjectSharingMode(sharing_mode)
    except ValueError as error:
        raise ValidationFailure("invalid project sharing mode") from error
    project = await lock_project_root(db, project_id)
    member = await db.get(ProjectMember, (project_id, user.id))
    if project is None or (
        user.role != "administrator" and (member is None or member.role is not ProjectRole.admin)
    ):
        raise ResourceUnavailable("project not found or project admin role required")
    if project.state is ProjectState.archived:
        raise ResourceUnavailable("archived project is read-only")
    if project.sharing_mode is ProjectSharingMode.live and mode is ProjectSharingMode.independent:
        assignments = list(
            (
                await db.scalars(
                    select(ProjectItem)
                    .where(ProjectItem.project_id == project_id)
                    .order_by(ProjectItem.id)
                    .with_for_update()
                )
            ).all()
        )
        for assignment in assignments:
            source = await db.get(Item, assignment.item_id, populate_existing=True)
            if source is None:
                raise ResourceUnavailable("project item source no longer exists")
            if source.owner_id is None:
                continue
            copy = await clone_item_for_project(db, source, user)
            assignment.item_id = copy.id
    project.sharing_mode = mode
    record_event(
        db, user.id, "project.sharing_mode.set", "project", project_id, detail={"mode": mode.value}
    )
    await db.commit()
    return project
