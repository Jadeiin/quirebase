from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from quirebase.audit import record_event
from quirebase.core.crypto import hash_password_async
from quirebase.core.errors import DomainError, ValidationFailure
from quirebase.models import SystemRole, User
from quirebase.operations.settings import get_effective_setting
from quirebase.workspaces import provision_initial_workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class RegistrationClosed(DomainError):
    pass


class RegistrationInvitationRequired(DomainError):
    pass


async def ensure_registration_allowed(db: AsyncSession, *, via_invitation: bool) -> None:
    policy = await get_effective_setting(db, "registration_policy", "invitation_only")
    # ``closed`` disables public self-registration, but an explicitly issued
    # instance Invitation remains an admission path.  The invitation-only
    # policy is the stricter mode that rejects public registration while still
    # allowing the same invitation path.
    if via_invitation:
        return
    if policy == "open":
        return
    if policy == "invitation_only":
        raise RegistrationInvitationRequired("registration requires an invitation")
    raise RegistrationClosed("registration is closed")


async def register_user(db: AsyncSession, username: str, password: str) -> User:
    await ensure_registration_allowed(db, via_invitation=False)
    cleaned_name = username.strip()
    if not cleaned_name or len(cleaned_name) > 120:
        raise ValidationFailure("username must contain 1 to 120 characters")
    try:
        encoded = await hash_password_async(password)
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    existing = await db.scalar(select(User).where(User.username == cleaned_name))
    if existing is not None:
        raise ValidationFailure(f"username '{cleaned_name}' is already taken")
    user = User(
        username=cleaned_name,
        password_hash=encoded,
        role=SystemRole.member.value,
        active=True,
    )
    db.add(user)
    try:
        await db.flush()
        await provision_initial_workspace(db, user)
        record_event(db, user.id, "auth.register", "user", user.id)
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise ValidationFailure(f"username '{cleaned_name}' is already taken") from error
    return user
