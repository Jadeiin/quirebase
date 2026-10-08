from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID  # ruff: ignore[typing-only-standard-library-import] - Pydantic exposes ProjectParticipantInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

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
    target: WorkspaceMember,
    *,
    action: str,
    resource_action: ResourceAction,
    authorization_role: str,
) -> ProjectParticipant:
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = (
        insert(ProjectParticipant)
        .values(
            workspace_id=workspace_id,
            project_id=project_id,
            workspace_member_id=target.id,
            user_id=target.user_id,
        )
        .on_conflict_do_nothing(index_elements=["workspace_id", "project_id", "user_id"])
        .returning(ProjectParticipant)
    )
    for _attempt in range(3):
        participant = await db.scalar(statement)
        inserted = participant is not None
        if inserted:
            break
        participant = await db.scalar(
            select(ProjectParticipant)
            .where(
                ProjectParticipant.workspace_id == workspace_id,
                ProjectParticipant.project_id == project_id,
                ProjectParticipant.workspace_member_id == target.id,
            )
            .with_for_update()
        )
        if participant is not None:
            break
        # A concurrent open leave can win between conflict detection and reread.
        # Retry this association only; root authority and mode remain guarded.
    else:
        raise ProjectParticipationConflict("Project participation changed concurrently")
    assert participant is not None
    if inserted:
        record_event(
            db,
            actor.id,
            action,
            "project_participant",
            participant.id,
            detail={"user_id": target.user_id},
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
    project = await lock_project_root(
        db, context, project_id, lock="shared", state=ProjectState.active
    )
    if project.participation is not ProjectParticipation.open:
        raise ProjectParticipationConflict("Only open Projects allow self-service participation")
    require_action(context, ResourceAction.project_participation_join, relation="open")
    return await _add_participant(
        db,
        context.actor,
        workspace_id,
        project_id,
        context.membership,
        action="project.participant.join",
        resource_action=ResourceAction.project_participation_join,
        authorization_role=context.role.value,
    )


async def leave_project(db: AsyncSession, user: User, workspace_id: UUID, project_id: UUID) -> None:
    """Remove the current User's opt-in from an open Project."""
    context = await lock_workspace_context(db, user, workspace_id)
    project = await lock_project_root(
        db, context, project_id, lock="shared", state=ProjectState.active
    )
    if project.participation is not ProjectParticipation.open:
        raise ProjectParticipationConflict("Only open Projects allow self-service participation")
    require_action(context, ResourceAction.project_participation_leave, relation="open")
    participant_id = await db.scalar(
        delete(ProjectParticipant)
        .where(
            ProjectParticipant.workspace_id == workspace_id,
            ProjectParticipant.project_id == project_id,
            ProjectParticipant.workspace_member_id == context.membership.id,
        )
        .returning(ProjectParticipant.id)
    )
    if participant_id is not None:
        record_event(
            db,
            context.actor.id,
            "project.participant.leave",
            "project_participant",
            participant_id,
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
    project = await lock_project_root(
        db, context, project_id, lock="shared", state=ProjectState.active
    )
    if project.participation is not ProjectParticipation.managed:
        raise ProjectParticipationConflict("Only managed Projects have curated participation")
    require_action(context, ResourceAction.project_participation_manage, relation="managed")
    target = (
        await db.execute(
            select(User, WorkspaceMember)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(
                User.username == username.strip(),
                User.active.is_(True),
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.state == WorkspaceMemberState.active,
                WorkspaceMember.terminated_at.is_(None),
            )
        )
    ).first()
    if target is None:
        raise ResourceNotFound("active Workspace member not found")
    target_user, target_member = target
    participant = ProjectParticipantInfo(user_id=target_user.id, username=target_user.username)
    await _add_participant(
        db,
        context.actor,
        workspace_id,
        project_id,
        target_member,
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
    # Removal revokes managed discovery, so retain the exclusive root guard.
    participant_id = await db.scalar(
        delete(ProjectParticipant)
        .where(
            ProjectParticipant.workspace_id == workspace_id,
            ProjectParticipant.project_id == project_id,
            ProjectParticipant.user_id == participant_user_id,
        )
        .returning(ProjectParticipant.id)
    )
    if participant_id is None:
        raise ResourceNotFound("Project participant not found")
    record_event(
        db,
        context.actor.id,
        "project.participant.remove",
        "project_participant",
        participant_id,
        detail={"user_id": participant_user_id},
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.project_participation_manage.value,
    )
    await db.commit()
