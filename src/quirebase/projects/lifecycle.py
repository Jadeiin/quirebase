from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete

from quirebase.access import (
    ResourceAction,
    require_project_access,
    require_project_context,
    require_project_participation_change,
    require_workspace_action,
)
from quirebase.audit import record_event
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.models import (
    Project,
    ProjectMember,
    ProjectParticipation,
    ProjectState,
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
    participation: ProjectParticipation | str,
) -> Project:
    normalized_name = _validate_name(name)
    normalized_description = _validate_description(description)
    try:
        normalized_participation = ProjectParticipation(participation)
    except ValueError as error:
        raise ValidationFailure("invalid Project participation") from error
    await lock_project_participation_workspace(db, workspace_id)
    project = await lock_project_root(db, project_id, workspace_id, state=ProjectState.active)
    context = await require_project_context(
        db, user, workspace_id, project_id, ResourceAction.project_update
    )
    participation_changed = normalized_participation is not project.participation
    if participation_changed:
        require_project_participation_change(
            context.workspace,
            project.participation,
            normalized_participation,
        )
    if normalized_participation is ProjectParticipation.workspace or (
        participation_changed and project.participation is ProjectParticipation.workspace
    ):
        await db.execute(
            delete(ProjectMember).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == project_id,
            )
        )
    if (
        participation_changed
        and normalized_participation is ProjectParticipation.open
        and project.participation is ProjectParticipation.workspace
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
        "participation": project.participation.value,
    }
    project.name = normalized_name
    project.description = normalized_description
    project.participation = normalized_participation
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
                "participation": normalized_participation.value,
            },
        },
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=context.workspace.role.value,
        authorization_resource_action=ResourceAction.project_update.value,
    )
    await db.commit()
    return project


async def rename_project(
    db: AsyncSession, user: User, workspace_id: str, project_id: str, name: str
) -> Project:
    await lock_project_participation_workspace(db, workspace_id)
    context = await require_project_context(
        db, user, workspace_id, project_id, ResourceAction.project_update
    )
    project = context.project
    return await update_project_settings(
        db,
        user,
        workspace_id,
        project_id,
        name=name,
        description=project.description,
        participation=project.participation,
    )


async def update_project_description(
    db: AsyncSession, user: User, workspace_id: str, project_id: str, description: str
) -> Project:
    await lock_project_participation_workspace(db, workspace_id)
    context = await require_project_context(
        db, user, workspace_id, project_id, ResourceAction.project_update
    )
    project = context.project
    return await update_project_settings(
        db,
        user,
        workspace_id,
        project_id,
        name=project.name,
        description=description,
        participation=project.participation,
    )


async def set_project_participation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    project_id: str,
    participation: ProjectParticipation | str,
) -> Project:
    await lock_project_participation_workspace(db, workspace_id)
    context = await require_project_context(
        db, user, workspace_id, project_id, ResourceAction.project_update
    )
    project = context.project
    return await update_project_settings(
        db,
        user,
        workspace_id,
        project_id,
        name=project.name,
        description=project.description,
        participation=participation,
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
    authorization_resource_action = (
        ResourceAction.project_archive
        if desired is ProjectState.archived
        else ResourceAction.project_restore
    )
    workspace = await require_workspace_action(
        db, user, workspace_id, authorization_resource_action
    )
    project = await lock_project_root(db, project_id, workspace_id)
    if project.workspace_id != workspace_id or project.state is ProjectState.deleted:
        raise ResourceUnavailable("Project not found")
    await require_project_access(db, workspace, project)
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
        authorization_resource_action=authorization_resource_action.value,
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
    context = await require_workspace_action(db, user, workspace_id, ResourceAction.project_delete)
    project = await lock_project_delete(db, project_id, workspace_id)
    if project.workspace_id != workspace_id or project.state is ProjectState.deleted:
        raise ResourceUnavailable("Project not found")
    await require_project_access(db, context, project)
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
        authorization_resource_action=ResourceAction.project_delete.value,
    )
    await db.commit()
