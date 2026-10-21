from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from advanced_alchemy.filters import LimitOffset
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError

from quirebase.access import (
    ResourceAction,
    WorkspaceContext,
    require_action,
    require_system_resource_action,
    require_workspace_membership,
    system_resource_action_allowed,
    workspace_decisions,
    workspace_member_relation,
)
from quirebase.audit import record_event
from quirebase.core.crypto import generate_token, token_hash
from quirebase.core.errors import (
    ResourceNotFound,
    ValidationFailure,
    WorkspaceLifecycleError,
)
from quirebase.core.persistence import select_page
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


@dataclass(frozen=True, slots=True)
class ReceivedWorkspaceInvitation:
    """Recipient-only admission state, without token material or Workspace content."""

    id: UUID
    workspace_id: UUID
    workspace_name: str
    inviter_username: str
    role: WorkspaceInvitationRole
    created_at: datetime
    expires_at: datetime
    state: Literal["pending", "accepted", "revoked", "expired"]
    can_accept: bool
    can_open: bool
    unavailable_reason: Literal["workspace_read_only", "current_member"] | None


async def _received_invitation_views(
    db: AsyncSession, actor: User, invitation_ids: list[UUID]
) -> list[ReceivedWorkspaceInvitation]:
    if not invitation_ids:
        return []
    rows = await db.execute(
        select(WorkspaceInvitation, Workspace, User.username, WorkspaceMember)
        .join(Workspace, Workspace.id == WorkspaceInvitation.workspace_id)
        .join(User, User.id == WorkspaceInvitation.invited_by)
        .outerjoin(
            WorkspaceMember,
            and_(
                WorkspaceMember.workspace_id == Workspace.id,
                WorkspaceMember.user_id == actor.id,
                WorkspaceMember.terminated_at.is_(None),
            ),
        )
        .where(
            WorkspaceInvitation.id.in_(invitation_ids),
            WorkspaceInvitation.user_id == actor.id,
        )
        .execution_options(populate_existing=True)
    )
    now = datetime.now(UTC)
    views = {}
    for invitation, workspace, inviter_username, member in rows:
        state: Literal["pending", "accepted", "revoked", "expired"] = "pending"
        if invitation.accepted_at is not None:
            state = "accepted"
        elif invitation.revoked_at is not None:
            state = "revoked"
        elif invitation.expires_at <= now:
            state = "expired"
        unavailable_reason: Literal["workspace_read_only", "current_member"] | None = None
        if (
            workspace.state is not WorkspaceState.active
            or workspace.governance_frozen_at is not None
        ):
            unavailable_reason = "workspace_read_only"
        elif member is not None:
            unavailable_reason = "current_member"
        views[invitation.id] = ReceivedWorkspaceInvitation(
            id=invitation.id,
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            inviter_username=inviter_username,
            role=invitation.role,
            created_at=invitation.created_at,
            expires_at=invitation.expires_at,
            state=state,
            can_accept=state == "pending"
            and unavailable_reason is None
            and system_resource_action_allowed(
                actor.role, "workspace_invitation", "accept", relation="own"
            ),
            can_open=state == "accepted"
            and member is not None
            and member.state is WorkspaceMemberState.active
            and ResourceAction.workspace_read
            in workspace_decisions(
                member.role,
                workspace.state,
                governance_frozen=workspace.governance_frozen_at is not None,
            ).allowed,
            unavailable_reason=unavailable_reason if state == "pending" else None,
        )
    return [views[invitation_id] for invitation_id in invitation_ids if invitation_id in views]


async def list_received_workspace_invitations(
    db: AsyncSession, actor: User, *, limit: int = 25, offset: int = 0
) -> tuple[list[ReceivedWorkspaceInvitation], int]:
    """List this User's pending invitations, including temporarily unavailable ones."""
    current_actor = await require_system_resource_action(
        db, actor, "workspace_invitation", "read", relation="own"
    )
    invitations, total = await select_page(
        db,
        select(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.user_id == current_actor.id,
            WorkspaceInvitation.accepted_at.is_(None),
            WorkspaceInvitation.revoked_at.is_(None),
            WorkspaceInvitation.expires_at > datetime.now(UTC),
        )
        .order_by(WorkspaceInvitation.created_at.desc(), WorkspaceInvitation.id.desc()),
        WorkspaceInvitation,
        LimitOffset(limit=limit, offset=offset),
    )
    return await _received_invitation_views(
        db, current_actor, [invitation.id for invitation in invitations]
    ), total


async def get_received_workspace_invitation(
    db: AsyncSession, actor: User, invitation_id: UUID
) -> ReceivedWorkspaceInvitation:
    """Reconcile a possibly completed accept without replaying admission or restoring access."""
    current_actor = await require_system_resource_action(
        db, actor, "workspace_invitation", "read", relation="own"
    )
    views = await _received_invitation_views(db, current_actor, [invitation_id])
    if not views:
        raise ResourceNotFound("Workspace invitation not found")
    return views[0]


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
    db: AsyncSession,
    context: WorkspaceContext,
    *,
    search: str = "",
    role: WorkspaceInvitationRole | Literal[""] = "",
    sort: Literal["username", "created", "expires"] = "created",
    direction: Literal["asc", "desc"] = "desc",
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[WorkspaceInvitation], int]:
    require_action(context, ResourceAction.workspace_invitation_read)
    columns = {
        "username": User.username,
        "created": WorkspaceInvitation.created_at,
        "expires": WorkspaceInvitation.expires_at,
    }
    if sort not in columns:
        raise ValidationFailure(f"unknown Workspace invitation sort: {sort}")
    if direction not in {"asc", "desc"}:
        raise ValidationFailure(f"unknown sort direction: {direction}")
    query = (
        select(WorkspaceInvitation)
        .join(User, User.id == WorkspaceInvitation.user_id)
        .where(
            WorkspaceInvitation.workspace_id == context.workspace_id,
            WorkspaceInvitation.accepted_at.is_(None),
            WorkspaceInvitation.revoked_at.is_(None),
            WorkspaceInvitation.expires_at > datetime.now(UTC),
        )
    )
    if term := search.strip():
        query = query.where(User.username.icontains(term, autoescape=True))
    if role:
        if role not in WorkspaceInvitationRole:
            raise ValidationFailure(f"unknown Workspace invitation role: {role}")
        query = query.where(WorkspaceInvitation.role == role)
    return await select_page(
        db,
        query.order_by(
            columns[sort].desc() if direction == "desc" else columns[sort].asc(),
            WorkspaceInvitation.id.desc() if direction == "desc" else WorkspaceInvitation.id.asc(),
        ),
        WorkspaceInvitation,
        LimitOffset(limit=limit, offset=offset),
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
        or workspace.governance_frozen_at is not None
    ):
        return None
    return invitation


async def accept_workspace_invitation(
    db: AsyncSession, actor: User, workspace_id: UUID, token: str
) -> WorkspaceMember:
    invitation_id = await db.scalar(
        select(WorkspaceInvitation.id).where(
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.token_hash == token_hash(token),
        )
    )
    if invitation_id is None:
        raise ResourceNotFound("Workspace invitation not found or expired")
    return await accept_workspace_invitation_by_id(db, actor, invitation_id)


async def accept_workspace_invitation_by_id(
    db: AsyncSession, actor: User, invitation_id: UUID
) -> WorkspaceMember:
    """Admit the authenticated recipient, sharing one transaction with token acceptance."""
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
    workspace_id = await db.scalar(
        select(WorkspaceInvitation.workspace_id).where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.user_id == current_actor.id,
        )
    )
    if workspace_id is None:
        raise ResourceNotFound("Workspace invitation not found or expired")
    workspace = await _lock_workspace(db, workspace_id)
    if workspace.state is not WorkspaceState.active or workspace.governance_frozen_at is not None:
        raise WorkspaceLifecycleError("Workspace is not accepting membership changes")
    invitation = await db.scalar(
        select(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.id == invitation_id,
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

    invitation_id = await db.scalar(
        select(WorkspaceInvitation.id).where(WorkspaceInvitation.token_hash == token_hash(token))
    )
    if invitation_id is None:
        raise ResourceNotFound("Workspace invitation not found or expired")
    return await accept_workspace_invitation_by_id(db, actor, invitation_id)


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
