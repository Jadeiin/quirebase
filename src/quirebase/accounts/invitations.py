from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.core.crypto import generate_token, token_hash
from quirebase.core.errors import DomainError, ResourceUnavailable, ValidationFailure
from quirebase.core.timezones import as_utc
from quirebase.models import Invitation, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class InvitationConflict(DomainError):
    pass


def get_valid_invitation(db: Session, token: str) -> Invitation | None:
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == token_hash(token)))
    if (
        invitation
        and invitation.accepted_at is None
        and as_utc(invitation.expires_at) > datetime.now(UTC)
    ):
        return invitation
    return None


def create_invitation(
    db: Session,
    creator: User,
    username: str,
    role: str = "member",
    expires_days: int = 7,
) -> tuple[Invitation, str]:
    if creator.role != "administrator":
        raise ResourceUnavailable("administration resource unavailable")
    normalized = username.strip()
    if not normalized or len(normalized) > 120 or role not in ("member", "administrator"):
        raise ValidationFailure("invalid username or role")
    if db.scalar(select(User).where(User.username == normalized)) or db.scalar(
        select(Invitation).where(Invitation.username == normalized)
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
    db.add(invitation)
    db.commit()
    return invitation, raw
