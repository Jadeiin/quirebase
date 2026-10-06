from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from quirebase.access import SystemAction, require_system_action
from quirebase.core.crypto import generate_token, token_hash
from quirebase.core.errors import DomainError, ResourceNotFound, ValidationFailure
from quirebase.models import Invitation, User

from ._persistence import InvitationRepository, UserService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class InvitationConflict(DomainError):
    pass


async def get_valid_invitation(db: AsyncSession, token: str) -> Invitation | None:
    invitation = await InvitationRepository(session=db).get_one_or_none(
        token_hash=token_hash(token)
    )
    if invitation and invitation.accepted_at is None and invitation.expires_at > datetime.now(UTC):
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
    if not normalized or len(normalized) > 120 or role not in ("member", "administrator"):
        raise ValidationFailure("invalid username or role")
    invitations = InvitationRepository(session=db)
    if await UserService(db).exists(username=normalized) or await invitations.exists(
        username=normalized
    ):
        raise InvitationConflict("username already exists or is invited")
    raw = generate_token(32)
    invitation = Invitation(
        token_hash=token_hash(raw),
        username=normalized,
        role=role,
        created_by=creator.id,
        expires_at=datetime.now(UTC) + timedelta(days=expires_days),
    )
    try:
        invitation = await invitations.add(invitation)
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise InvitationConflict("username already exists or is invited") from error
    return invitation, raw
