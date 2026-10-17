from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from quirebase.access import SystemAction, require_system_action
from quirebase.audit import record_event
from quirebase.core.crypto import generate_token, token_hash
from quirebase.core.errors import DomainError, ResourceNotFound, ValidationFailure
from quirebase.models import Invitation, SystemRole, User

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class InvitationConflict(DomainError):
    pass


async def get_valid_invitation(db: AsyncSession, token: str) -> Invitation | None:
    invitation = await db.scalar(
        select(Invitation)
        .where(Invitation.token_hash == token_hash(token))
        .execution_options(populate_existing=True)
    )
    if (
        invitation
        and invitation.accepted_at is None
        and invitation.revoked_at is None
        and invitation.expires_at > datetime.now(UTC)
    ):
        return invitation
    return None


async def create_invitation(
    db: AsyncSession,
    creator: User,
    username: str,
    role: str = "member",
    expires_days: int = 7,
) -> tuple[Invitation, str]:
    creator = await require_system_action(
        db,
        creator,
        SystemAction.invitations_create,
        lock="shared",
        message="resource not found",
        denied_error=ResourceNotFound,
    )
    normalized = username.strip()
    if (
        not normalized
        or len(normalized) > 120
        or role not in SystemRole
        or not 1 <= expires_days <= 365
    ):
        raise ValidationFailure("invalid username or role")
    if await db.scalar(select(User.id).where(User.username == normalized)):
        raise InvitationConflict("username already exists or is invited")
    now = datetime.now(UTC)
    # Expired links still reserve the partial unique index. Retire them in this
    # transaction before inserting a replacement, preserving their history.
    expired = await db.scalars(
        update(Invitation)
        .where(
            Invitation.username == normalized,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at <= now,
        )
        .values(revoked_at=now)
        .returning(Invitation)
        .execution_options(populate_existing=True)
    )
    for expired_invitation in expired:
        record_event(
            db,
            creator.id,
            "invitation.revoke",
            "invitation",
            expired_invitation.id,
            detail={"reason": "expired"},
            authorization_resource_action=SystemAction.invitations_create.value,
        )
    invitation, raw = _new_invitation(creator, normalized, SystemRole(role), expires_days)
    try:
        db.add(invitation)
        await db.flush()
        record_event(
            db,
            creator.id,
            "invitation.create",
            "invitation",
            invitation.id,
            detail={"role": invitation.role.value},
            authorization_resource_action=SystemAction.invitations_create.value,
        )
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise InvitationConflict("username already exists or is invited") from error
    return invitation, raw


def _new_invitation(
    creator: User, username: str, role: SystemRole, expires_days: int = 7
) -> tuple[Invitation, str]:
    raw = generate_token(32)
    invitation = Invitation(
        token_hash=token_hash(raw),
        username=username,
        role=role,
        created_by=creator.id,
        expires_at=datetime.now(UTC) + timedelta(days=expires_days),
    )
    return invitation, raw


async def revoke_invitation(db: AsyncSession, admin: User, invitation_id: UUID) -> None:
    admin = await require_system_action(
        db,
        admin,
        SystemAction.invitations_revoke,
        lock="shared",
        message="resource not found",
        denied_error=ResourceNotFound,
    )
    revoked = await db.scalar(
        update(Invitation)
        .where(
            Invitation.id == invitation_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
        .returning(Invitation)
        .execution_options(populate_existing=True)
    )
    if revoked is None:
        invitation = await db.get(Invitation, invitation_id, populate_existing=True)
        if invitation is None or invitation.accepted_at is not None:
            raise ResourceNotFound("invitation not found")
    else:
        record_event(
            db,
            admin.id,
            "invitation.revoke",
            "invitation",
            invitation_id,
            authorization_resource_action=SystemAction.invitations_revoke.value,
        )
    await db.commit()


async def reissue_invitation(
    db: AsyncSession, admin: User, invitation_id: UUID
) -> tuple[Invitation, str]:
    admin = await require_system_action(
        db,
        admin,
        SystemAction.invitations_reissue,
        lock="shared",
        message="resource not found",
        denied_error=ResourceNotFound,
    )
    # The conditional write arbitrates accept/revoke/reissue on both databases.
    # A repeated request against the old record cannot mint another link.
    previous = await db.scalar(
        update(Invitation)
        .where(
            Invitation.id == invitation_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
        .returning(Invitation)
        .execution_options(populate_existing=True)
    )
    if previous is None:
        raise ResourceNotFound("invitation not found or already used")
    if await db.scalar(select(User.id).where(User.username == previous.username)):
        await db.rollback()
        raise InvitationConflict("username already exists")
    invitation, raw = _new_invitation(admin, previous.username, previous.role)
    try:
        db.add(invitation)
        await db.flush()
        for action, target_id, detail in (
            ("invitation.revoke", previous.id, {"reason": "reissued"}),
            ("invitation.create", invitation.id, {"role": invitation.role.value}),
            ("invitation.reissue", previous.id, {"replacement_invitation_id": invitation.id}),
        ):
            record_event(
                db,
                admin.id,
                action,
                "invitation",
                target_id,
                detail=detail,
                authorization_resource_action=SystemAction.invitations_reissue.value,
            )
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise InvitationConflict("username already exists or is invited") from error
    return invitation, raw
