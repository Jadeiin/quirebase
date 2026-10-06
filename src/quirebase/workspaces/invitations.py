from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from quirebase.access import (
    ResourceAction,
    WorkspaceContext,
    require_action,
    require_system_resource_action,
    require_workspace_membership,
    workspace_member_relation,
)
from quirebase.audit import record_event
from quirebase.core.crypto import generate_token, token_hash
from quirebase.core.errors import (
    ResourceNotFound,
    ValidationFailure,
    WorkspaceLifecycleError,
)
from quirebase.models import (
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceInvitationRole,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

from ._locking import _lock_workspace


async def invite_workspace_member(
    db: AsyncSession,
    actor: User,
    workspace_id: UUID,
    username: str,
    role: WorkspaceInvitationRole | str,
    *,
    expires_at: datetime | None = None,
) -> tuple[WorkspaceInvitation, str]:
    try:
        requested = WorkspaceInvitationRole(role)
    except ValueError as error:
        raise ValidationFailure(
            "Workspace invitations require an admin, editor, reviewer or viewer role"
        ) from error
    normalized_username = username.strip()
    if not normalized_username:
        raise ValidationFailure("Workspace invitations require an exact active username")
    # Account governance locks Users before Workspaces. Hold a shared User lock
    # so deactivation either commits first and is observed here, or waits until
    # the invitation transaction has committed.
    target = await db.scalar(
        select(User)
        .where(User.username == normalized_username, User.active.is_(True))
        .execution_options(populate_existing=True)
        .with_for_update(read=True)
    )
    if target is None or not target.active:
        raise ValidationFailure("Workspace invitations require an exact active username")
    await _lock_workspace(db, workspace_id)
    context = await require_workspace_membership(db, actor, workspace_id)
    require_action(
        context,
        ResourceAction.workspace_invitation_create,
        relation=workspace_member_relation(requested.value),
    )
    now = datetime.now(UTC)
    if expires_at is None:
        normalized_expiry = now + timedelta(days=7)
    else:
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValidationFailure("Workspace invitation expiry must include a timezone")
        normalized_expiry = expires_at.astimezone(UTC)
    if normalized_expiry <= now or normalized_expiry > now + timedelta(days=365):
        raise ValidationFailure("Workspace invitation expiry must be within the next 365 days")
    existing = await db.scalar(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == target.id,
            WorkspaceMember.terminated_at.is_(None),
        )
    )
    if existing is not None:
        raise ValidationFailure("User is already a current Workspace member")
    await _revoke_pending_invitations(db, workspace_id, target.id)
    raw = generate_token(32)
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id,
        user_id=target.id,
        role=requested,
        token_hash=token_hash(raw),
        invited_by=actor.id,
        expires_at=normalized_expiry,
    )
    db.add(invitation)
    await db.flush()
    record_event(
        db,
        actor.id,
        "workspace.invitation.create",
        "workspace_invitation",
        invitation.id,
        detail={"user_id": target.id, "role": requested.value},
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.workspace_invitation_create.value,
    )
    await db.commit()
    return invitation, raw


async def list_workspace_invitations(
    db: AsyncSession, context: WorkspaceContext
) -> list[WorkspaceInvitation]:
    require_action(context, ResourceAction.workspace_invitation_read)
    workspace_id = context.workspace_id
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


async def get_workspace_invitation_by_token(
    db: AsyncSession, token: str
) -> WorkspaceInvitation | None:
    """Resolve a valid Workspace invitation for the public acceptance page."""

    invitation = await db.scalar(
        select(WorkspaceInvitation)
        .where(WorkspaceInvitation.token_hash == token_hash(token))
        .execution_options(populate_existing=True)
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= datetime.now(UTC)
    ):
        return None
    workspace = await db.get(Workspace, invitation.workspace_id, populate_existing=True)
    if (
        workspace is None
        or workspace.state is not WorkspaceState.active
        or workspace.governance_suspended_at is not None
    ):
        return None
    return invitation


async def accept_workspace_invitation(
    db: AsyncSession, actor: User, workspace_id: UUID, token: str
) -> WorkspaceMember:
    current_actor = await require_system_resource_action(
        db,
        actor,
        "workspace_invitation",
        "accept",
        relation="own",
        lock="shared",
        message="Workspace invitation not found or expired",
        denied_error=ResourceNotFound,
    )
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
        or invitation.expires_at <= datetime.now(UTC)
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
            role=WorkspaceRole(invitation.role),
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
        authorization_role=current_actor.role,
        authorization_resource_action="workspace_invitation.accept",
    )
    await db.commit()
    return member


async def accept_workspace_invitation_by_token(
    db: AsyncSession, actor: User, token: str
) -> WorkspaceMember:
    """Accept a single-use invitation without requiring prior Workspace membership."""

    workspace_id = await db.scalar(
        select(WorkspaceInvitation.workspace_id).where(
            WorkspaceInvitation.token_hash == token_hash(token)
        )
    )
    if workspace_id is None:
        raise ResourceNotFound("Workspace invitation not found or expired")
    return await accept_workspace_invitation(db, actor, workspace_id, token)


async def _revoke_pending_invitations(
    db: AsyncSession, workspace_id: UUID, user_id: UUID, *, except_id: UUID | None = None
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
    db: AsyncSession, actor: User, workspace_id: UUID, invitation_id: UUID
) -> None:
    await _lock_workspace(db, workspace_id)
    context = await require_workspace_membership(db, actor, workspace_id)
    require_action(context, ResourceAction.workspace_invitation_revoke)
    invitation = await db.scalar(
        select(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.workspace_id == workspace_id,
        )
        .execution_options(populate_existing=True)
    )
    if invitation is None or invitation.accepted_at is not None:
        raise ResourceNotFound("Workspace invitation not found")
    now = datetime.now(UTC)
    if invitation.revoked_at is not None or invitation.expires_at <= now:
        await db.commit()
        return
    invitation.revoked_at = now
    record_event(
        db,
        actor.id,
        "workspace.invitation.revoke",
        "workspace_invitation",
        invitation.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.workspace_invitation_revoke.value,
    )
    await db.commit()
