from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete

from quirebase.access import (
    ResourceAction,
    lock_workspace_context,
    require_action,
    require_project_participation_change,
)
from quirebase.audit import record_event
from quirebase.core.errors import ValidationFailure
from quirebase.models import (
    Project,
    ProjectParticipant,
    ProjectParticipation,
    ProjectState,
    User,
)

from ._locking import lock_project_root

if TYPE_CHECKING:
    from uuid import UUID

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
    workspace_id: UUID,
    project_id: UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    participation: ProjectParticipation | str | None = None,
) -> Project:
    context = await lock_workspace_context(db, user, workspace_id)
    project = await lock_project_root(db, context, project_id, state=ProjectState.active)
    require_action(context, ResourceAction.project_update)
    normalized_name = _validate_name(project.name if name is None else name)
    normalized_description = _validate_description(
        project.description if description is None else description
    )
    try:
        normalized_participation = ProjectParticipation(
            project.participation if participation is None else participation
        )
    except ValueError as error:
        raise ValidationFailure("invalid Project participation") from error
    participation_changed = normalized_participation is not project.participation
    if participation_changed:
        require_project_participation_change(
            context,
            project.participation,
            normalized_participation,
        )
    if participation_changed and ProjectParticipation.workspace in {
        project.participation,
        normalized_participation,
    }:
        await db.execute(
            delete(ProjectParticipant).where(
                ProjectParticipant.workspace_id == workspace_id,
                ProjectParticipant.project_id == project_id,
            )
        )
    if (
        participation_changed
        and normalized_participation is ProjectParticipation.open
        and project.participation is ProjectParticipation.workspace
    ):
        db.add(
            ProjectParticipant(
                workspace_id=workspace_id,
                project_id=project_id,
                workspace_member_id=context.membership.id,
                user_id=context.actor_id,
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
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.project_update.value,
    )
    await db.commit()
    return project


async def rename_project(
    db: AsyncSession, user: User, workspace_id: UUID, project_id: UUID, name: str
) -> Project:
    return await update_project_settings(db, user, workspace_id, project_id, name=name)


async def update_project_description(
    db: AsyncSession, user: User, workspace_id: UUID, project_id: UUID, description: str
) -> Project:
    return await update_project_settings(
        db, user, workspace_id, project_id, description=description
    )


async def set_project_participation(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    project_id: UUID,
    participation: ProjectParticipation | str,
) -> Project:
    return await update_project_settings(
        db, user, workspace_id, project_id, participation=participation
    )


async def set_project_state(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    project_id: UUID,
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
    workspace = await lock_workspace_context(db, user, workspace_id)
    project = await lock_project_root(db, workspace, project_id)
    require_action(workspace, authorization_resource_action)
    if project.state is desired:
        await db.commit()
        return project
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
    workspace_id: UUID,
    project_id: UUID,
    confirmation: str,
) -> None:
    context = await lock_workspace_context(db, user, workspace_id)
    project = await lock_project_root(db, context, project_id)
    require_action(context, ResourceAction.project_delete)
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
