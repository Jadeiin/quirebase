from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.accounts.invitations import InvitationConflict
from quirebase.accounts.sessions import create_login_session
from quirebase.accounts.throttling import (
    LoginThrottled,
    check_login_throttle,
    clear_login_failures,
    record_login_failure,
)
from quirebase.audit import record_event
from quirebase.core.crypto import hash_password_async, token_hash, verify_password_async
from quirebase.core.errors import DomainError, ResourceNotFound, ValidationFailure
from quirebase.core.timezones import as_utc
from quirebase.models import Invitation, LoginSession, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class AuthenticationFailure(DomainError):
    pass


class InvalidCredentials(AuthenticationFailure):
    pass


async def resolve_api_token_user(db: AsyncSession, subject: str) -> User:
    """Resolve a verified API Token subject to an active local User."""
    user = await db.get(User, subject)
    if user is None or not user.active:
        raise AuthenticationFailure("access token subject is not an active user")
    return user


async def authenticate_user(
    db: AsyncSession,
    identity: str,
    username: str,
    password: str,
    session_days: int = 30,
) -> tuple[LoginSession, str]:
    try:
        await check_login_throttle(db, identity)
    except LoginThrottled:
        record_event(
            db,
            None,
            "auth.login.throttled",
            "user",
            detail={"identity_hash": identity},
        )
        await db.commit()
        raise

    user = await db.scalar(select(User).where(User.username == username))
    password_valid = bool(
        user is not None
        and user.active
        and await verify_password_async(user.password_hash, password)
    )
    if not password_valid:
        await record_login_failure(db, identity)
        record_event(
            db,
            None,
            "auth.login.failed",
            "user",
            user.id if user else None,
            detail={"identity_hash": identity},
        )
        await db.commit()
        raise InvalidCredentials("Invalid credentials")

    assert user is not None
    await clear_login_failures(db, identity)
    login_session, raw = await create_login_session(db, user, session_days=session_days)
    record_event(
        db,
        user.id,
        "auth.login.succeeded",
        "login_session",
        login_session.id,
        detail={"identity_hash": identity},
    )
    await db.commit()
    return login_session, raw


async def logout(db: AsyncSession, user: User, login_session: LoginSession) -> None:
    record_event(db, user.id, "auth.logout", "login_session", login_session.id)
    await db.delete(login_session)
    await db.commit()


async def accept_invitation(db: AsyncSession, token: str, password: str) -> User:
    invitation = await db.scalar(
        select(Invitation).where(Invitation.token_hash == token_hash(token))
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or as_utc(invitation.expires_at) <= datetime.now(UTC)
    ):
        raise ResourceNotFound("invitation not found or expired")
    if await db.scalar(select(User).where(User.username == invitation.username)):
        raise InvitationConflict("username already exists")
    try:
        encoded = await hash_password_async(password)
    except ValueError as error:
        raise ValidationFailure(str(error)) from error

    user = User(username=invitation.username, password_hash=encoded, role=invitation.role)
    db.add(user)
    invitation.accepted_at = datetime.now(UTC)
    await db.flush()
    record_event(db, user.id, "invitation.accept", "user", user.id)
    await db.commit()
    return user


async def change_own_password(
    db: AsyncSession, user: User, current_password: str, new_password: str
) -> None:
    if not await verify_password_async(user.password_hash, current_password):
        raise InvalidCredentials("Current password incorrect")
    try:
        user.password_hash = await hash_password_async(new_password)
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    record_event(db, user.id, "account.password.changed", "user", user.id)
    await db.commit()
