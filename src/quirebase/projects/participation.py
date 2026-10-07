from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID  # ruff: ignore[typing-only-standard-library-import] - Pydantic exposes ProjectParticipantInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from quirebase.access import (
    ResourceAction,
    lock_workspace_context,
    require_action,
)
from quirebase.audit import record_event
from quirebase.core.errors import DomainError, ResourceNotFound
from quirebase.models import (
    ProjectParticipant,
    ProjectParticipation,
    ProjectState,
    User,
    WorkspaceMember,
    WorkspaceMemberState,
)

from ._locking import lock_project_root

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ProjectParticipationConflict(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectParticipantInfo:
    user_id: UUID
    username: str


async def _add_participant(
    db: AsyncSession,
    actor: User,
    workspace_id: UUID,
    project_id: UUID,
    target: User,
    *,
    action: str,
    resource_action: ResourceAction,
    authorization_role: str,
) -> ProjectParticipant:
    existing = await db.scalar(
        select(ProjectParticipant).where(
            ProjectParticipant.workspace_id == workspace_id,
            ProjectParticipant.project_id == project_id,
            ProjectParticipant.user_id == target.id,
        )
    )
    if existing is not None:
        return existing
    participant = ProjectParticipant(
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=target.id,
    )
    db.add(participant)
    try:
        await db.flush()
    except IntegrityError as error:
        raise ProjectParticipationConflict("Project participant already exists") from error
    record_event(
        db,
        actor.id,
        action,
        "project_participant",
        participant.id,
        detail={"user_id": target.id},
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=authorization_role,
        authorization_resource_action=resource_action.value,
    )
    await db.commit()
    return participant


async def join_project(
    db: AsyncSession, user: User, workspace_id: UUID, project_id: UUID
) -> ProjectParticipant:
    """Record an active Workspace member's opt-in to an open Project."""
    context = await lock_workspace_context(db, user, workspace_id)
    project = await lock_project_root(db, context, project_id, state=ProjectState.active)
    if project.participation is not ProjectParticipation.open:
        raise ProjectParticipationConflict("Only open Projects allow self-service participation")
    require_action(context, ResourceAction.project_participation_join, relation="open")
    return await _add_participant(
        db,
        context.actor,
        workspace_id,
        project_id,
        context.actor,
        action="project.participant.join",
        resource_action=ResourceAction.project_participation_join,
        authorization_role=context.role.value,
    )


async def leave_project(db: AsyncSession, user: User, workspace_id: UUID, project_id: UUID) -> None:
    """Remove the current User's opt-in from an open Project."""
    context = await lock_workspace_context(db, user, workspace_id)
    project = await lock_project_root(db, context, project_id, state=ProjectState.active)
    if project.participation is not ProjectParticipation.open:
        raise ProjectParticipationConflict("Only open Projects allow self-service participation")
    require_action(context, ResourceAction.project_participation_leave, relation="open")
    participant = await db.scalar(
        select(ProjectParticipant).where(
            ProjectParticipant.workspace_id == workspace_id,
            ProjectParticipant.project_id == project_id,
            ProjectParticipant.user_id == context.actor.id,
        )
    )
    if participant is None:
        return
    await db.delete(participant)
    record_event(
        db,
        context.actor.id,
        "project.participant.leave",
        "project_participant",
        participant.id,
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.project_participation_leave.value,
    )
    await db.commit()


async def add_project_participant(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    project_id: UUID,
    username: str,
) -> ProjectParticipantInfo:
    """Add an active Workspace member to a managed Project's working context."""
    context = await lock_workspace_context(db, user, workspace_id)
    project = await lock_project_root(db, context, project_id, state=ProjectState.active)
    if project.participation is not ProjectParticipation.managed:
        raise ProjectParticipationConflict("Only managed Projects have curated participation")
    require_action(context, ResourceAction.project_participation_manage, relation="managed")
    target = await db.scalar(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(
            User.username == username.strip(),
            User.active.is_(True),
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.state == WorkspaceMemberState.active,
            WorkspaceMember.terminated_at.is_(None),
        )
    )
    if target is None:
        raise ResourceNotFound("active Workspace member not found")
    participant = ProjectParticipantInfo(user_id=target.id, username=target.username)
    await _add_participant(
        db,
        context.actor,
        workspace_id,
        project_id,
        target,
        action="project.participant.add",
        resource_action=ResourceAction.project_participation_manage,
        authorization_role=context.role.value,
    )
    return participant


async def remove_project_participant(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    project_id: UUID,
    participant_user_id: UUID,
) -> None:
    """Remove a participant from a managed Project without a minimum-count invariant."""
    context = await lock_workspace_context(db, user, workspace_id)
    project = await lock_project_root(db, context, project_id, state=ProjectState.active)
    if project.participation is not ProjectParticipation.managed:
        raise ProjectParticipationConflict("Only managed Projects have curated participation")
    require_action(context, ResourceAction.project_participation_manage, relation="managed")
    target = await db.scalar(
        select(ProjectParticipant).where(
            ProjectParticipant.workspace_id == workspace_id,
            ProjectParticipant.project_id == project_id,
            ProjectParticipant.user_id == participant_user_id,
        )
    )
    if target is None:
        raise ResourceNotFound("Project participant not found")
    await db.delete(target)
    record_event(
        db,
        context.actor.id,
        "project.participant.remove",
        "project_participant",
        target.id,
        detail={"user_id": participant_user_id},
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.project_participation_manage.value,
    )
    await db.commit()
