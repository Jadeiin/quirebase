from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from quirebase.access import Capability, require_project_context, require_workspace_capability
from quirebase.audit import record_event
from quirebase.core.errors import DomainError, ResourceNotFound, ValidationFailure
from quirebase.models import (
    ProjectMember,
    ProjectState,
    ProjectVisibility,
    User,
    WorkspaceMember,
    WorkspaceMemberState,
)

from ._locking import lock_project_membership_workspace, lock_project_root

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ProjectMemberConflict(DomainError):
    pass


async def add_project_member(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    project_id: str,
    username: str,
) -> ProjectMember:
    await lock_project_membership_workspace(db, workspace_id)
    workspace = await require_workspace_capability(
        db, user, workspace_id, Capability.projects_members_manage
    )
    await lock_project_root(db, project_id, workspace_id, state=ProjectState.active)
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
    # An owner/admin outside a members-visible Project can explicitly join it
    # before exercising Project-scoped governance. Adding someone else still
    # requires the ordinary Project visibility gate.
    if target.id != user.id:
        await require_project_context(
            db, user, workspace_id, project_id, Capability.projects_members_manage
        )
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
        user.id,
        "project.member.add",
        "project_member",
        member.id,
        detail={"user_id": target.id},
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=workspace.role.value,
        authorization_capability=Capability.projects_members_manage.value,
    )
    await db.commit()
    return member


async def remove_project_member(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    project_id: str,
    member_user_id: str,
) -> None:
    await lock_project_membership_workspace(db, workspace_id)
    project = await lock_project_root(db, project_id, workspace_id)
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.projects_members_manage
    )
    target = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == member_user_id,
        )
    )
    if target is None:
        raise ResourceNotFound("Project member not found")
    if project.visibility is ProjectVisibility.members:
        remaining_active = await db.scalar(
            select(func.count(ProjectMember.id))
            .join(User, User.id == ProjectMember.user_id)
            .join(
                WorkspaceMember,
                (WorkspaceMember.workspace_id == ProjectMember.workspace_id)
                & (WorkspaceMember.user_id == ProjectMember.user_id),
            )
            .where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == project_id,
                ProjectMember.user_id != member_user_id,
                User.active.is_(True),
                WorkspaceMember.state == WorkspaceMemberState.active,
                WorkspaceMember.terminated_at.is_(None),
            )
        )
        if not remaining_active:
            raise ValidationFailure("members-visible Project must retain a Project member")
    await db.delete(target)
    record_event(
        db,
        user.id,
        "project.member.remove",
        "project_member",
        target.id,
        detail={"user_id": member_user_id},
        workspace_id=workspace_id,
        project_id=project_id,
        authorization_role=context.workspace.role.value,
        authorization_capability=Capability.projects_members_manage.value,
    )
    await db.commit()
