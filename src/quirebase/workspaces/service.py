from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from quirebase.access import Capability, require_workspace_capability, role_has_capability
from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.crypto import generate_token, token_hash
from quirebase.core.errors import (
    PermissionDenied,
    ResourceNotFound,
    ValidationFailure,
    WorkspaceLifecycleError,
)
from quirebase.core.timezones import as_utc
from quirebase.core.workflows import DOCUMENT_CLEANUP_QUEUE, durable_operations
from quirebase.models import (
    Attachment,
    ExportArtifact,
    FileRevision,
    ImportBatch,
    Item,
    PdfAnnotation,
    PdfAnnotationObject,
    PdfAnnotationReply,
    Project,
    ProjectMember,
    ProjectState,
    ProjectVisibility,
    SystemRole,
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.operations.settings import get_effective_setting

from .workflows import WORKSPACE_OBJECT_CLEANUP_WORKFLOW

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _workspace_name(user: User) -> str:
    return f"{user.username}'s Workspace"


async def provision_initial_workspace(db: AsyncSession, user: User) -> Workspace:
    """Create the ordinary Workspace included in a new User's creation transaction."""
    locked = await db.scalar(
        select(User)
        .where(User.id == user.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if locked is None:
        raise ResourceNotFound("User not found")
    existing = await db.scalar(
        select(Workspace.id).where(Workspace.created_by == locked.id).limit(1)
    )
    if existing is not None:
        raise ValidationFailure("User has already created a Workspace; use explicit repair/create")

    workspace = Workspace(name=_workspace_name(locked), created_by=locked.id, owner_id=locked.id)
    db.add(workspace)
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=locked.id,
            role=WorkspaceRole.owner,
            state=WorkspaceMemberState.active,
            invited_by=locked.id,
        )
    )
    record_event(
        db,
        locked.id,
        "workspace.initial.provision",
        "workspace",
        workspace.id,
        workspace_id=workspace.id,
        authorization_role=WorkspaceRole.owner.value,
        authorization_capability="workspace.initial.provision",
    )
    await db.flush()
    return workspace


async def repair_initial_workspace(
    db: AsyncSession, actor: User, user_id: str | None = None
) -> Workspace:
    """Explicitly give a User with no current Workspace access a new Workspace."""
    target_id = user_id or actor.id
    if target_id != actor.id and actor.role != SystemRole.administrator.value:
        raise PermissionDenied("instance administrator required")
    user = await db.scalar(select(User).where(User.id == target_id).with_for_update())
    if user is None or not user.active:
        raise ResourceNotFound("active User not found")
    existing = await db.scalar(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.state == WorkspaceMemberState.active,
            WorkspaceMember.terminated_at.is_(None),
            Workspace.state != WorkspaceState.deleted,
        )
        .order_by(Workspace.created_at, Workspace.id)
        .limit(1)
    )
    if existing is not None:
        return existing
    owned = await db.scalar(
        select(Workspace)
        .where(Workspace.owner_id == user.id, Workspace.state != WorkspaceState.deleted)
        .order_by(Workspace.created_at, Workspace.id)
        .with_for_update()
    )
    if owned is not None:
        membership = await db.scalar(
            select(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == owned.id,
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.terminated_at.is_(None),
            )
            .with_for_update()
        )
        if membership is None:
            db.add(
                WorkspaceMember(
                    workspace_id=owned.id,
                    user_id=user.id,
                    role=WorkspaceRole.owner,
                    state=WorkspaceMemberState.active,
                    invited_by=actor.id,
                )
            )
        else:
            membership.role = WorkspaceRole.owner
            membership.state = WorkspaceMemberState.active
            membership.suspended_at = None
        record_event(
            db,
            actor.id,
            "workspace.repair.membership",
            "workspace",
            owned.id,
            workspace_id=owned.id,
            authorization_capability="workspace.repair.membership",
        )
        await db.commit()
        return owned
    workspace = Workspace(name=_workspace_name(user), created_by=user.id, owner_id=user.id)
    db.add(workspace)
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.owner,
            state=WorkspaceMemberState.active,
            invited_by=actor.id,
        )
    )
    record_event(
        db,
        actor.id,
        "workspace.repair.create",
        "workspace",
        workspace.id,
        workspace_id=workspace.id,
        authorization_capability="workspace.repair.create",
    )
    await db.commit()
    return workspace


async def create_workspace(
    db: AsyncSession,
    actor: User,
    name: str,
    *,
    owner_id: str | None = None,
) -> Workspace:
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 240:
        raise ValidationFailure("Workspace name must contain 1 to 240 characters")
    policy = await get_effective_setting(db, "workspace_creation_policy", "admins_only")
    requested_owner_id = owner_id if policy == "admins_only" else actor.id
    user_ids = {actor.id}
    if requested_owner_id is not None:
        user_ids.add(requested_owner_id)
    locked_users = {
        user.id: user
        for user in (
            await db.scalars(
                select(User)
                .where(User.id.in_(user_ids))
                .order_by(User.id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).all()
    }
    current_actor = locked_users.get(actor.id)
    if current_actor is None or not current_actor.active:
        raise PermissionDenied("active User required")
    administrator = current_actor.role == SystemRole.administrator.value
    if policy == "admins_only":
        if not administrator:
            raise PermissionDenied("Workspace creation is restricted to instance administrators")
        if owner_id is None:
            raise ValidationFailure("an active initial owner is required")
    elif policy == "members_allowed":
        if owner_id is not None:
            raise ValidationFailure("members-created Workspaces are owned by their creator")
    else:
        raise ValidationFailure("invalid Workspace creation policy")
    owner = locked_users.get(requested_owner_id) if requested_owner_id is not None else None
    if owner is None or not owner.active:
        raise ValidationFailure("initial owner must be an active User")
    workspace = Workspace(name=cleaned, created_by=actor.id, owner_id=owner.id)
    db.add(workspace)
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=owner.id,
            role=WorkspaceRole.owner,
            state=WorkspaceMemberState.active,
            invited_by=actor.id,
        )
    )
    record_event(
        db,
        actor.id,
        "workspace.create",
        "workspace",
        workspace.id,
        workspace_id=workspace.id,
        authorization_role=WorkspaceRole.owner.value if owner.id == actor.id else None,
        authorization_capability="workspace.create",
    )
    await db.commit()
    return workspace


async def list_workspaces(db: AsyncSession, actor: User) -> list[tuple[Workspace, WorkspaceMember]]:
    if not actor.active:
        return []
    rows = await db.execute(
        select(Workspace, WorkspaceMember)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == actor.id,
            WorkspaceMember.state == WorkspaceMemberState.active,
            WorkspaceMember.terminated_at.is_(None),
            Workspace.state != WorkspaceState.deleted,
        )
        .order_by(Workspace.name, Workspace.id)
    )
    return list(rows.tuples())


async def get_workspace(
    db: AsyncSession, actor: User, workspace_id: str
) -> tuple[Workspace, WorkspaceMember]:
    context = await require_workspace_capability(db, actor, workspace_id, Capability.workspace_read)
    return context.workspace, context.membership


async def _lock_workspace(db: AsyncSession, workspace_id: str) -> Workspace:
    workspace = await db.scalar(
        select(Workspace)
        .where(Workspace.id == workspace_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if workspace is None or workspace.state is WorkspaceState.deleted:
        raise ResourceNotFound("Workspace not found")
    return workspace


async def update_workspace(
    db: AsyncSession, actor: User, workspace_id: str, name: str
) -> Workspace:
    workspace = await _lock_workspace(db, workspace_id)
    context = await require_workspace_capability(
        db, actor, workspace_id, Capability.workspace_settings_manage
    )
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 240:
        raise ValidationFailure("Workspace name must contain 1 to 240 characters")
    workspace.name = cleaned
    record_event(
        db,
        actor.id,
        "workspace.update",
        "workspace",
        workspace.id,
        workspace_id=workspace.id,
        authorization_role=context.role.value,
        authorization_capability=Capability.workspace_settings_manage.value,
    )
    await db.commit()
    return workspace


async def list_workspace_members(
    db: AsyncSession, actor: User, workspace_id: str
) -> list[WorkspaceMember]:
    await require_workspace_capability(db, actor, workspace_id, Capability.workspace_read)
    return list(
        (
            await db.scalars(
                select(WorkspaceMember)
                .where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.terminated_at.is_(None),
                )
                .order_by(WorkspaceMember.created_at, WorkspaceMember.id)
            )
        ).all()
    )


async def invite_workspace_member(
    db: AsyncSession,
    actor: User,
    workspace_id: str,
    user_id: str,
    role: WorkspaceRole | str,
    *,
    expires_days: int = 7,
) -> tuple[WorkspaceInvitation, str]:
    await _lock_workspace(db, workspace_id)
    context = await require_workspace_capability(
        db, actor, workspace_id, Capability.workspace_members_manage
    )
    requested = WorkspaceRole(role)
    if requested in {WorkspaceRole.owner, WorkspaceRole.admin}:
        raise ValidationFailure("owner/admin roles are assigned through governance operations")
    target = await db.get(User, user_id)
    if target is None or not target.active:
        raise ValidationFailure("Workspace invitations require an existing active User")
    existing = await db.scalar(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.terminated_at.is_(None),
        )
    )
    if existing is not None:
        raise ValidationFailure("User is already a current Workspace member")
    raw = generate_token(32)
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id,
        user_id=user_id,
        role=requested,
        token_hash=token_hash(raw),
        invited_by=actor.id,
        expires_at=datetime.now(UTC) + timedelta(days=expires_days),
    )
    db.add(invitation)
    record_event(
        db,
        actor.id,
        "workspace.invitation.create",
        "workspace_invitation",
        invitation.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=Capability.workspace_members_manage.value,
    )
    await db.commit()
    return invitation, raw


async def list_workspace_invitations(
    db: AsyncSession, actor: User, workspace_id: str
) -> list[WorkspaceInvitation]:
    await require_workspace_capability(db, actor, workspace_id, Capability.workspace_members_manage)
    return list(
        (
            await db.scalars(
                select(WorkspaceInvitation)
                .where(
                    WorkspaceInvitation.workspace_id == workspace_id,
                    WorkspaceInvitation.accepted_at.is_(None),
                    WorkspaceInvitation.revoked_at.is_(None),
                    WorkspaceInvitation.expires_at > datetime.now(UTC),
                )
                .order_by(WorkspaceInvitation.created_at, WorkspaceInvitation.id)
            )
        ).all()
    )


async def accept_workspace_invitation(
    db: AsyncSession, actor: User, workspace_id: str, token: str
) -> WorkspaceMember:
    current_actor = await db.scalar(
        select(User)
        .where(User.id == actor.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if current_actor is None or not current_actor.active:
        raise ResourceNotFound("Workspace invitation not found or expired")
    hashed = token_hash(token)
    observed = await db.scalar(
        select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == hashed)
    )
    if observed is None or observed.workspace_id != workspace_id:
        raise ResourceNotFound("Workspace invitation not found or expired")
    workspace = await _lock_workspace(db, workspace_id)
    if (
        workspace.state is not WorkspaceState.active
        or workspace.governance_suspended_at is not None
    ):
        raise WorkspaceLifecycleError("Workspace is not accepting membership changes")
    invitation = await db.scalar(
        select(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.token_hash == hashed,
            WorkspaceInvitation.workspace_id == workspace_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if (
        invitation is None
        or invitation.user_id != current_actor.id
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or as_utc(invitation.expires_at) <= datetime.now(UTC)
    ):
        raise ResourceNotFound("Workspace invitation not found or expired")
    member = await db.scalar(
        select(WorkspaceMember)
        .where(
            WorkspaceMember.workspace_id == invitation.workspace_id,
            WorkspaceMember.user_id == current_actor.id,
            WorkspaceMember.terminated_at.is_(None),
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if member is None:
        member = WorkspaceMember(
            workspace_id=invitation.workspace_id,
            user_id=current_actor.id,
            role=invitation.role,
            state=WorkspaceMemberState.active,
            invited_by=invitation.invited_by,
        )
        db.add(member)
    else:
        raise ValidationFailure("User is already a current Workspace member")
    invitation.accepted_at = datetime.now(UTC)
    try:
        await db.flush()
    except IntegrityError as error:
        await db.rollback()
        raise ValidationFailure("Workspace membership could not be admitted") from error
    await _revoke_pending_invitations(
        db, invitation.workspace_id, current_actor.id, except_id=invitation.id
    )
    record_event(
        db,
        current_actor.id,
        "workspace.invitation.accept",
        "workspace_member",
        member.id,
        workspace_id=member.workspace_id,
        authorization_role=member.role.value,
        authorization_capability="workspace.invitation.accept",
    )
    await db.commit()
    return member


async def _revoke_pending_invitations(
    db: AsyncSession, workspace_id: str, user_id: str, *, except_id: str | None = None
) -> None:
    statement = select(WorkspaceInvitation).where(
        WorkspaceInvitation.workspace_id == workspace_id,
        WorkspaceInvitation.user_id == user_id,
        WorkspaceInvitation.accepted_at.is_(None),
        WorkspaceInvitation.revoked_at.is_(None),
    )
    if except_id is not None:
        statement = statement.where(WorkspaceInvitation.id != except_id)
    pending = (await db.scalars(statement.execution_options(populate_existing=True))).all()
    revoked_at = datetime.now(UTC)
    for invitation in pending:
        invitation.revoked_at = revoked_at


async def revoke_workspace_invitation(
    db: AsyncSession, actor: User, workspace_id: str, invitation_id: str
) -> None:
    await _lock_workspace(db, workspace_id)
    context = await require_workspace_capability(
        db, actor, workspace_id, Capability.workspace_members_manage
    )
    invitation = await db.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.workspace_id == workspace_id,
        )
    )
    if invitation is None or invitation.accepted_at is not None:
        raise ResourceNotFound("Workspace invitation not found")
    invitation.revoked_at = datetime.now(UTC)
    record_event(
        db,
        actor.id,
        "workspace.invitation.revoke",
        "workspace_invitation",
        invitation.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=Capability.workspace_members_manage.value,
    )
    await db.commit()


async def _current_member(
    db: AsyncSession, workspace_id: str, membership_id: str
) -> WorkspaceMember:
    member = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.id == membership_id,
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.terminated_at.is_(None),
        )
    )
    if member is None:
        raise ResourceNotFound("Workspace member not found")
    return member


async def _ensure_member_not_last_active_project_participant(
    db: AsyncSession, workspace_id: str, member: WorkspaceMember
) -> None:
    """Keep every members-visible Project reachable by an active participant."""
    active_membership = aliased(WorkspaceMember)
    project_ids = (
        await db.scalars(
            select(ProjectMember.project_id)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.user_id == member.user_id,
                Project.workspace_id == workspace_id,
                Project.visibility == ProjectVisibility.members,
                Project.state != ProjectState.deleted,
            )
        )
    ).all()
    for project_id in project_ids:
        active_count = await db.scalar(
            select(func.count(ProjectMember.id))
            .join(User, User.id == ProjectMember.user_id)
            .join(
                active_membership,
                (active_membership.workspace_id == ProjectMember.workspace_id)
                & (active_membership.user_id == ProjectMember.user_id),
            )
            .where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == project_id,
                ProjectMember.user_id != member.user_id,
                User.active.is_(True),
                active_membership.state == WorkspaceMemberState.active,
                active_membership.terminated_at.is_(None),
            )
        )
        if not active_count:
            raise ValidationFailure("members-visible Project must retain an active Project member")


async def set_workspace_member_role(
    db: AsyncSession,
    actor: User,
    workspace_id: str,
    membership_id: str,
    role: WorkspaceRole | str,
) -> WorkspaceMember:
    requested = WorkspaceRole(role)
    capability = (
        Capability.workspace_admins_manage
        if requested is WorkspaceRole.admin
        else Capability.workspace_members_manage
    )
    workspace = await _lock_workspace(db, workspace_id)
    context = await require_workspace_capability(db, actor, workspace_id, capability)
    member = await _current_member(db, workspace_id, membership_id)
    if member.user_id == workspace.owner_id or requested is WorkspaceRole.owner:
        raise ValidationFailure("use ownership transfer for the owner role")
    if member.role is WorkspaceRole.admin and requested is not WorkspaceRole.admin:
        context = await require_workspace_capability(
            db, actor, workspace_id, Capability.workspace_admins_manage
        )
        capability = Capability.workspace_admins_manage
    member.role = requested
    record_event(
        db,
        actor.id,
        "workspace.member.role",
        "workspace_member",
        member.id,
        detail={"role": requested.value},
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=capability.value,
    )
    await db.commit()
    return member


async def suspend_workspace_member(
    db: AsyncSession, actor: User, workspace_id: str, membership_id: str
) -> WorkspaceMember:
    workspace = await _lock_workspace(db, workspace_id)
    context = await require_workspace_capability(
        db, actor, workspace_id, Capability.workspace_members_manage
    )
    member = await _current_member(db, workspace_id, membership_id)
    if member.user_id == workspace.owner_id:
        raise PermissionDenied("transfer Workspace ownership before suspending the owner")
    if member.role is WorkspaceRole.admin:
        context = await require_workspace_capability(
            db, actor, workspace_id, Capability.workspace_admins_manage
        )
    effective_capability = (
        Capability.workspace_admins_manage
        if member.role is WorkspaceRole.admin
        else Capability.workspace_members_manage
    )
    if member.state is WorkspaceMemberState.active:
        await _ensure_member_not_last_active_project_participant(db, workspace_id, member)
    member.state = WorkspaceMemberState.suspended
    member.suspended_at = datetime.now(UTC)
    await _revoke_pending_invitations(db, workspace_id, member.user_id)
    record_event(
        db,
        actor.id,
        "workspace.member.suspend",
        "workspace_member",
        member.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=effective_capability.value,
    )
    await db.commit()
    return member


async def reactivate_workspace_member(
    db: AsyncSession, actor: User, workspace_id: str, membership_id: str
) -> WorkspaceMember:
    await _lock_workspace(db, workspace_id)
    context = await require_workspace_capability(
        db, actor, workspace_id, Capability.workspace_members_manage
    )
    member = await _current_member(db, workspace_id, membership_id)
    if member.role is WorkspaceRole.admin:
        context = await require_workspace_capability(
            db, actor, workspace_id, Capability.workspace_admins_manage
        )
    effective_capability = (
        Capability.workspace_admins_manage
        if member.role is WorkspaceRole.admin
        else Capability.workspace_members_manage
    )
    member.state = WorkspaceMemberState.active
    member.suspended_at = None
    record_event(
        db,
        actor.id,
        "workspace.member.reactivate",
        "workspace_member",
        member.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=effective_capability.value,
    )
    await db.commit()
    return member


async def terminate_workspace_member(
    db: AsyncSession, actor: User, workspace_id: str, membership_id: str
) -> None:
    workspace = await _lock_workspace(db, workspace_id)
    context = await require_workspace_capability(
        db, actor, workspace_id, Capability.workspace_members_manage
    )
    member = await _current_member(db, workspace_id, membership_id)
    if member.user_id == workspace.owner_id:
        raise PermissionDenied("transfer Workspace ownership before removing the owner")
    if member.role is WorkspaceRole.admin:
        context = await require_workspace_capability(
            db, actor, workspace_id, Capability.workspace_admins_manage
        )
    effective_capability = (
        Capability.workspace_admins_manage
        if member.role is WorkspaceRole.admin
        else Capability.workspace_members_manage
    )
    if member.state is WorkspaceMemberState.active:
        await _ensure_member_not_last_active_project_participant(db, workspace_id, member)
    await db.execute(
        delete(ProjectMember).where(
            ProjectMember.workspace_id == workspace_id,
            ProjectMember.user_id == member.user_id,
        )
    )
    member.terminated_at = datetime.now(UTC)
    await _revoke_pending_invitations(db, workspace_id, member.user_id)
    record_event(
        db,
        actor.id,
        "workspace.member.terminate",
        "workspace_member",
        member.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=effective_capability.value,
    )
    await db.commit()


async def transfer_workspace_ownership(
    db: AsyncSession, actor: User, workspace_id: str, target_membership_id: str
) -> Workspace:
    workspace = await _lock_workspace(db, workspace_id)
    context = await require_workspace_capability(
        db, actor, workspace_id, Capability.workspace_transfer
    )
    target = await _current_member(db, workspace_id, target_membership_id)
    if target.state is not WorkspaceMemberState.active:
        raise ValidationFailure("new owner must be an active Workspace member")
    target_user = await db.get(User, target.user_id)
    if target_user is None or not target_user.active:
        raise ValidationFailure("new owner must be an active User")
    current = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == workspace.owner_id,
            WorkspaceMember.terminated_at.is_(None),
        )
    )
    if current is None:
        raise ValidationFailure("Workspace owner membership is inconsistent")
    if target.id == current.id:
        return workspace
    current.role = WorkspaceRole.admin
    await db.flush()
    target.role = WorkspaceRole.owner
    workspace.owner_id = target.user_id
    record_event(
        db,
        actor.id,
        "workspace.ownership.transfer",
        "workspace",
        workspace.id,
        detail={"previous_owner_id": current.user_id, "owner_id": target.user_id},
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=Capability.workspace_transfer.value,
    )
    await db.commit()
    return workspace


async def archive_workspace(db: AsyncSession, actor: User, workspace_id: str) -> Workspace:
    workspace = await _lock_workspace(db, workspace_id)
    context = await require_workspace_capability(
        db, actor, workspace_id, Capability.workspace_archive
    )
    workspace.state = WorkspaceState.archived
    workspace.archived_at = datetime.now(UTC)
    record_event(
        db,
        actor.id,
        "workspace.archive",
        "workspace",
        workspace.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=Capability.workspace_archive.value,
    )
    await db.commit()
    return workspace


async def restore_workspace(db: AsyncSession, actor: User, workspace_id: str) -> Workspace:
    # Restore is the one mutation intentionally authorized while archived.
    workspace = await _lock_workspace(db, workspace_id)
    if workspace.governance_suspended_at is not None:
        raise WorkspaceLifecycleError("Workspace governance is suspended")
    context = await require_workspace_capability(db, actor, workspace_id, Capability.workspace_read)
    if not role_has_capability(context.role, Capability.workspace_archive):
        raise PermissionDenied("Workspace archive capability required")
    workspace.state = WorkspaceState.active
    workspace.archived_at = None
    record_event(
        db,
        actor.id,
        "workspace.restore",
        "workspace",
        workspace.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=Capability.workspace_archive.value,
    )
    await db.commit()
    return workspace


async def permanently_delete_workspace(
    db: AsyncSession, actor: User, workspace_id: str
) -> Workspace:
    # Deletion is permitted only from archived state, so membership and role are checked separately.
    workspace = await _lock_workspace(db, workspace_id)
    if workspace.governance_suspended_at is not None:
        raise WorkspaceLifecycleError("Workspace governance is suspended")
    context = await require_workspace_capability(db, actor, workspace_id, Capability.workspace_read)
    if not role_has_capability(context.role, Capability.workspace_delete):
        raise PermissionDenied("Workspace delete capability required")
    if workspace.state is not WorkspaceState.archived:
        raise ValidationFailure("Workspace must be archived before permanent deletion")
    now = datetime.now(UTC)
    archived_at = as_utc(workspace.archived_at) if workspace.archived_at else None
    retention = timedelta(days=get_settings().workspace_delete_retention_days)
    if archived_at is None or archived_at > now - retention:
        raise WorkspaceLifecycleError("Workspace archive retention period has not elapsed")

    object_keys = set(
        (
            await db.scalars(
                select(FileRevision.object_key).where(FileRevision.workspace_id == workspace_id)
            )
        ).all()
    )
    object_keys.update(
        key
        for key in (
            await db.scalars(
                select(FileRevision.thumbnail_object_key).where(
                    FileRevision.workspace_id == workspace_id,
                    FileRevision.thumbnail_object_key.is_not(None),
                )
            )
        ).all()
        if key
    )
    object_keys.update(
        (
            await db.scalars(
                select(Attachment.object_key).where(Attachment.workspace_id == workspace_id)
            )
        ).all()
    )
    object_keys.update(
        (
            await db.scalars(
                select(ExportArtifact.object_key).where(ExportArtifact.workspace_id == workspace_id)
            )
        ).all()
    )
    for records_json in (
        await db.scalars(
            select(ImportBatch.records).where(ImportBatch.workspace_id == workspace_id)
        )
    ).all():
        try:
            records = json.loads(records_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValidationFailure("Workspace Import Batch records are invalid") from error
        if not isinstance(records, list):
            raise ValidationFailure("Workspace Import Batch records are invalid")
        for record in records:
            if isinstance(record, dict) and isinstance((pdf := record.get("_pdf")), dict):
                key = pdf.get("object_key")
                if isinstance(key, str):
                    object_keys.add(key)

    annotation_ids = list(
        (
            await db.scalars(
                select(PdfAnnotation.id).where(PdfAnnotation.workspace_id == workspace_id)
            )
        ).all()
    )
    annotation_ids.extend(
        (
            await db.scalars(
                select(PdfAnnotationReply.id).where(PdfAnnotationReply.workspace_id == workspace_id)
            )
        ).all()
    )
    # SQLite FTS tables have no foreign keys; PostgreSQL's projections do, but
    # explicit removal keeps both dialects identical before the root cascade.
    await db.execute(
        text(
            "DELETE FROM revision_search WHERE item_id IN "
            "(SELECT id FROM items WHERE workspace_id = :workspace_id)"
        ),
        {"workspace_id": workspace_id},
    )
    await db.execute(
        text(
            "DELETE FROM item_search WHERE item_id IN "
            "(SELECT id FROM items WHERE workspace_id = :workspace_id)"
        ),
        {"workspace_id": workspace_id},
    )

    workspace.state = WorkspaceState.deleted
    workspace.deleted_at = now
    record_event(
        db,
        actor.id,
        "workspace.delete",
        "workspace",
        workspace.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_capability=Capability.workspace_delete.value,
    )
    sorted_keys = sorted(object_keys)
    for start in range(0, len(sorted_keys), 200):
        batch_keys = sorted_keys[start : start + 200]
        workflow_id = f"workspace-objects-cleanup:{uuid4()}"
        await durable_operations().enqueue_in_transaction(
            db,
            WORKSPACE_OBJECT_CLEANUP_WORKFLOW,
            workflow_id,
            actor.id,
            workspace_id,
            batch_keys,
            queue_name=DOCUMENT_CLEANUP_QUEUE,
            workflow_id=workflow_id,
            attributes={
                "capability": "workspaces",
                "operation": "workspace_delete_cleanup",
                "actor_id": actor.id,
                "workspace_id": workspace_id,
                "object_keys": batch_keys,
            },
        )
    # Deleting the root is the database fence for in-flight stale mutations:
    # every Workspace-owned aggregate is connected by cascading foreign keys.
    await db.delete(workspace)
    await db.flush()
    for start in range(0, len(annotation_ids), 500):
        await db.execute(
            delete(PdfAnnotationObject).where(
                PdfAnnotationObject.id.in_(annotation_ids[start : start + 500])
            )
        )
    await db.commit()
    return workspace


def _require_instance_administrator(actor: User) -> None:
    if actor.role != SystemRole.administrator.value or not actor.active:
        raise ResourceNotFound("Workspace not found")


async def list_workspaces_for_governance(db: AsyncSession, actor: User) -> list[Workspace]:
    _require_instance_administrator(actor)
    return list((await db.scalars(select(Workspace).order_by(Workspace.created_at.desc()))).all())


async def suspend_workspace_governance(
    db: AsyncSession, actor: User, workspace_id: str
) -> Workspace:
    _require_instance_administrator(actor)
    workspace = await _lock_workspace(db, workspace_id)
    if workspace.state is WorkspaceState.deleted:
        raise ResourceNotFound("Workspace not found")
    workspace.governance_suspended_at = datetime.now(UTC)
    workspace.governance_suspended_by = actor.id
    record_event(
        db,
        actor.id,
        "admin.workspace.suspend",
        "workspace",
        workspace.id,
        workspace_id=workspace.id,
        authorization_role=SystemRole.administrator.value,
        authorization_capability="workspace.governance.suspend",
        source="http",
    )
    await db.commit()
    return workspace


async def recover_workspace_governance(
    db: AsyncSession, actor: User, workspace_id: str
) -> Workspace:
    _require_instance_administrator(actor)
    workspace = await _lock_workspace(db, workspace_id)
    if workspace.state is WorkspaceState.deleted:
        raise ResourceNotFound("Workspace not found")
    workspace.governance_suspended_at = None
    workspace.governance_suspended_by = None
    record_event(
        db,
        actor.id,
        "admin.workspace.recover",
        "workspace",
        workspace.id,
        workspace_id=workspace.id,
        authorization_role=SystemRole.administrator.value,
        authorization_capability="workspace.governance.recover",
        source="http",
    )
    await db.commit()
    return workspace


async def read_workspace_items_break_glass(
    db: AsyncSession,
    actor: User,
    workspace_id: str,
    reason: str,
    *,
    limit: int = 100,
) -> list[Item]:
    """Perform one reason-bound, read-only administrative content access."""
    _require_instance_administrator(actor)
    reason = reason.strip()
    if len(reason) < 10:
        raise ValidationFailure("break-glass reason must contain at least 10 characters")
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None or workspace.state is WorkspaceState.deleted:
        raise ResourceNotFound("Workspace not found")
    items = list(
        (
            await db.scalars(
                select(Item)
                .where(Item.workspace_id == workspace_id)
                .order_by(Item.updated_at.desc())
                .limit(limit)
            )
        ).all()
    )
    record_event(
        db,
        actor.id,
        "admin.workspace.break_glass.read",
        "workspace",
        workspace_id,
        detail={"reason": reason, "resource": "items", "result_count": len(items)},
        workspace_id=workspace_id,
        authorization_role=SystemRole.administrator.value,
        authorization_capability="workspace.break_glass.read",
        result="succeeded",
        source="break_glass",
    )
    await db.commit()
    return items
