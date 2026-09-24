from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from quirebase.access import Capability, require_workspace_capability
from quirebase.audit import record_event
from quirebase.core.errors import DomainError, ResourceNotFound, WorkspaceLifecycleError
from quirebase.models import (
    ProjectMember,
    ProjectState,
    ProjectVisibility,
    User,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceState,
)

from ._locking import lock_project_participation_workspace, lock_project_root

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ProjectMemberConflict(DomainError):
    pass


async def _active_workspace_user(db: AsyncSession, workspace_id: str, user_id: str) -> User | None:
    return await db.scalar(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(
            User.id == user_id,
            User.active.is_(True),
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.state == WorkspaceMemberState.active,
            WorkspaceMember.terminated_at.is_(None),
        )
    )


async def _add_participant(
    db: AsyncSession,
    actor: User,
    workspace_id: str,
    project_id: str,
    target: User,
    *,
    action: str,
    capability: Capability,
    authorization_role: str,
) -> ProjectMember:
    existing = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == target.id,
        )
    )
    if existing is not None:
        return existing
    member = ProjectMember(
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=target.id,
    )
    db.add(member)
    try:
        await db.flush()
    except IntegrityError as error:
        raise ProjectMemberConflict("Project member already exists") from error
    record_event(
        db,
        actor.id,
        action,
        "project_member",
        member.id,
        detail={"user_id": target.id},
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=authorization_role,
        authorization_capability=capability.value,
    )
    await db.commit()
    return member


async def join_project(
    db: AsyncSession, user: User, workspace_id: str, project_id: str
) -> ProjectMember:
    """Record an active Workspace member's opt-in to an open Project."""
    await lock_project_participation_workspace(db, workspace_id)
    context = await require_workspace_capability(db, user, workspace_id, Capability.workspace_read)
    if (
        context.workspace.state is not WorkspaceState.active
        or context.workspace.governance_suspended_at is not None
    ):
        raise WorkspaceLifecycleError("Workspace is read-only")
    project = await lock_project_root(db, project_id, workspace_id, state=ProjectState.active)
    if project.visibility is not ProjectVisibility.open:
        raise ProjectMemberConflict("Only open Projects allow self-service participation")
    return await _add_participant(
        db,
        context.actor,
        workspace_id,
        project_id,
        context.actor,
        action="project.member.join",
        capability=Capability.workspace_read,
        authorization_role=context.role.value,
    )


async def leave_project(db: AsyncSession, user: User, workspace_id: str, project_id: str) -> None:
    """Remove the current User's opt-in from an open Project."""
    await lock_project_participation_workspace(db, workspace_id)
    context = await require_workspace_capability(db, user, workspace_id, Capability.workspace_read)
    if (
        context.workspace.state is not WorkspaceState.active
        or context.workspace.governance_suspended_at is not None
    ):
        raise WorkspaceLifecycleError("Workspace is read-only")
    project = await lock_project_root(db, project_id, workspace_id, state=ProjectState.active)
    if project.visibility is not ProjectVisibility.open:
        raise ProjectMemberConflict("Only open Projects allow self-service participation")
    member = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == context.actor.id,
        )
    )
    if member is None:
        return
    await db.delete(member)
    record_event(
        db,
        context.actor.id,
        "project.member.leave",
        "project_member",
        member.id,
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=context.role.value,
        authorization_capability=Capability.workspace_read.value,
    )
    await db.commit()


async def add_project_member(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    project_id: str,
    username: str,
) -> ProjectMember:
    """Add an active Workspace member to a managed Project's working context."""
    await lock_project_participation_workspace(db, workspace_id)
    context = await require_workspace_capability(
        db, user, workspace_id, Capability.projects_members_manage
    )
    project = await lock_project_root(db, project_id, workspace_id, state=ProjectState.active)
    if project.visibility is not ProjectVisibility.managed:
        raise ProjectMemberConflict("Only managed Projects have curated participation")
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
    return await _add_participant(
        db,
        context.actor,
        workspace_id,
        project_id,
        target,
        action="project.member.add",
        capability=Capability.projects_members_manage,
        authorization_role=context.role.value,
    )


async def remove_project_member(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    project_id: str,
    member_user_id: str,
) -> None:
    """Remove a participant from a managed Project without a minimum-count invariant."""
    await lock_project_participation_workspace(db, workspace_id)
    context = await require_workspace_capability(
        db, user, workspace_id, Capability.projects_members_manage
    )
    project = await lock_project_root(db, project_id, workspace_id, state=ProjectState.active)
    if project.visibility is not ProjectVisibility.managed:
        raise ProjectMemberConflict("Only managed Projects have curated participation")
    target = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == member_user_id,
        )
    )
    if target is None:
        raise ResourceNotFound("Project member not found")
    await db.delete(target)
    record_event(
        db,
        context.actor.id,
        "project.member.remove",
        "project_member",
        target.id,
        detail={"user_id": member_user_id},
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=context.role.value,
        authorization_capability=Capability.projects_members_manage.value,
    )
    await db.commit()
