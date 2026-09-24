from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete

from quirebase.access import (
    Capability,
    require,
    require_project_context,
    require_workspace_capability,
)
from quirebase.audit import record_event
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.models import (
    Project,
    ProjectMember,
    ProjectState,
    ProjectVisibility,
    User,
)

from ._locking import (
    lock_project_delete,
    lock_project_participation_workspace,
    lock_project_root,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def validate_project_state(value: ProjectState | str) -> ProjectState:
    try:
        return ProjectState(value)
    except ValueError as error:
        raise ValidationFailure("invalid Project state") from error


def _validate_name(name: str) -> str:
    normalized = name.strip()
    if not normalized or len(normalized) > 240:
        raise ValidationFailure("Project name must contain 1 to 240 characters")
    return normalized


def _validate_description(description: str) -> str:
    normalized = description.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > 2000:
        raise ValidationFailure("Project description is too long")
    return normalized


async def update_project_settings(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    project_id: str,
    *,
    name: str,
    description: str,
    visibility: ProjectVisibility | str,
) -> Project:
    normalized_name = _validate_name(name)
    normalized_description = _validate_description(description)
    try:
        normalized_visibility = ProjectVisibility(visibility)
    except ValueError as error:
        raise ValidationFailure("invalid Project visibility") from error
    await lock_project_participation_workspace(db, workspace_id)
    project = await lock_project_root(db, project_id, workspace_id, state=ProjectState.active)
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.projects_manage
    )
    visibility_changed = normalized_visibility is not project.visibility
    if visibility_changed and (
        project.visibility is ProjectVisibility.managed
        or normalized_visibility is ProjectVisibility.managed
    ):
        require(context.workspace, Capability.projects_members_manage)
    if normalized_visibility is ProjectVisibility.workspace or (
        visibility_changed and project.visibility is ProjectVisibility.workspace
    ):
        await db.execute(
            delete(ProjectMember).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == project_id,
            )
        )
    if (
        visibility_changed
        and normalized_visibility is ProjectVisibility.open
        and project.visibility is ProjectVisibility.workspace
    ):
        db.add(
            ProjectMember(
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=user.id,
            )
        )
    old = {
        "name": project.name,
        "description": project.description,
        "visibility": project.visibility.value,
    }
    project.name = normalized_name
    project.description = normalized_description
    project.visibility = normalized_visibility
    record_event(
        db,
        user.id,
        "project.settings.update",
        "project",
        project.id,
        detail={
            "old": old,
            "new": {
                "name": normalized_name,
                "description": normalized_description,
                "visibility": normalized_visibility.value,
            },
        },
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=context.workspace.role.value,
        authorization_capability=Capability.projects_manage.value,
    )
    await db.commit()
    return project


async def rename_project(
    db: AsyncSession, user: User, workspace_id: str, project_id: str, name: str
) -> Project:
    await lock_project_participation_workspace(db, workspace_id)
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.projects_manage
    )
    project = context.project
    return await update_project_settings(
        db,
        user,
        workspace_id,
        project_id,
        name=name,
        description=project.description,
        visibility=project.visibility,
    )


async def update_project_description(
    db: AsyncSession, user: User, workspace_id: str, project_id: str, description: str
) -> Project:
    await lock_project_participation_workspace(db, workspace_id)
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.projects_manage
    )
    project = context.project
    return await update_project_settings(
        db,
        user,
        workspace_id,
        project_id,
        name=project.name,
        description=description,
        visibility=project.visibility,
    )


async def set_project_visibility(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    project_id: str,
    visibility: ProjectVisibility | str,
) -> Project:
    await lock_project_participation_workspace(db, workspace_id)
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.projects_manage
    )
    project = context.project
    return await update_project_settings(
        db,
        user,
        workspace_id,
        project_id,
        name=project.name,
        description=project.description,
        visibility=visibility,
    )


async def set_project_state(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    project_id: str,
    state: ProjectState | str,
) -> Project:
    desired = validate_project_state(state)
    if desired is ProjectState.deleted:
        raise ValidationFailure("use Project delete for permanent deletion")
    workspace = await require_workspace_capability(
        db, user, workspace_id, Capability.projects_manage
    )
    project = await lock_project_root(db, project_id, workspace_id)
    if project.workspace_id != workspace_id or project.state is ProjectState.deleted:
        raise ResourceUnavailable("Project not found")
    workspace = await require_workspace_capability(
        db, user, workspace_id, Capability.projects_manage
    )
    project.state = desired
    record_event(
        db,
        user.id,
        f"project.{desired.value}",
        "project",
        project_id,
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=workspace.role.value,
        authorization_capability=Capability.projects_manage.value,
    )
    await db.commit()
    return project


async def delete_project(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    project_id: str,
    confirmation: str,
) -> None:
    context = await require_workspace_capability(db, user, workspace_id, Capability.projects_delete)
    project = await lock_project_delete(db, project_id, workspace_id)
    if project.workspace_id != workspace_id or project.state is ProjectState.deleted:
        raise ResourceUnavailable("Project not found")
    if confirmation.strip() != project.name:
        raise ValidationFailure("Project name confirmation does not match")
    project.state = ProjectState.deleted
    record_event(
        db,
        user.id,
        "project.delete",
        "project",
        project.id,
        detail={"name": project.name},
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=context.role.value,
        authorization_capability=Capability.projects_delete.value,
    )
    await db.commit()
