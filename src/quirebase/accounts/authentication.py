from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from quirebase.access import require_system_resource_action
from quirebase.accounts.invitations import InvitationConflict
from quirebase.accounts.sessions import _create_login_session
from quirebase.accounts.throttling import (
    LoginThrottled,
    _check_login_throttle,
    _clear_login_failures,
    _record_login_failure,
)
from quirebase.audit import record_event
from quirebase.core.crypto import (
    compare_digest,
    hash_password_async,
    token_hash,
    verify_and_update_password,
    verify_password_async,
)
from quirebase.core.errors import DomainError, ResourceNotFound, ValidationFailure
from quirebase.models import Invitation, LoginSession, User
from quirebase.workspaces import provision_initial_workspace

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class AuthenticationFailure(DomainError):
    pass


class InvalidCredentials(AuthenticationFailure):
    pass


async def resolve_api_token_user(db: AsyncSession, subject: UUID) -> User:
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
        await _check_login_throttle(db, identity)
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
    user_id = user.id if user is not None else None
    encoded = user.password_hash if user is not None and user.active else None
    # End the initial read/expired-window cleanup before expensive password work.
    await db.commit()
    password_valid, upgraded = (
        await verify_and_update_password(encoded, password)
        if encoded is not None
        else (False, None)
    )
    if password_valid:
        user = await db.scalar(
            select(User)
            .where(User.id == user_id)
            .execution_options(populate_existing=True)
            # NO KEY UPDATE serializes signing with password/status changes and
            # allows this transaction to install an opportunistic hash upgrade.
            .with_for_update(key_share=True)
        )
        assert encoded is not None
        password_valid = (
            user is not None
            and user.active
            and compare_digest(user.password_hash.hash_string, encoded.hash_string)
        )
    if not password_valid:
        await _record_login_failure(db, identity)
        record_event(
            db,
            None,
            "auth.login.failed",
            "user",
            user_id,
            detail={"identity_hash": identity},
        )
        await db.commit()
        raise InvalidCredentials("Invalid credentials")

    assert user is not None
    if upgraded is not None:
        user.password_hash = upgraded
    await _clear_login_failures(db, identity)
    login_session, raw = await _create_login_session(db, user, session_days=session_days)
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
    from quirebase.accounts.registration import ensure_registration_allowed

    await ensure_registration_allowed(db, via_invitation=True)
    invitation_token_hash = token_hash(token)
    invitation = await db.scalar(
        select(Invitation).where(Invitation.token_hash == invitation_token_hash)
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.expires_at <= datetime.now(UTC)
    ):
        raise ResourceNotFound("invitation not found or expired")
    if await db.scalar(select(User).where(User.username == invitation.username)):
        raise InvitationConflict("username already exists")
    try:
        encoded = await hash_password_async(password)
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    invitation = await db.scalar(
        select(Invitation)
        .where(Invitation.token_hash == invitation_token_hash)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.expires_at <= datetime.now(UTC)
    ):
        raise ResourceNotFound("invitation not found or expired")
    if await db.scalar(select(User).where(User.username == invitation.username)):
        raise InvitationConflict("username already exists")
    user = User(username=invitation.username, password_hash=encoded, role=invitation.role)
    invitation.accepted_at = datetime.now(UTC)
    try:
        db.add(user)
        await db.flush()
        await provision_initial_workspace(db, user)
        record_event(db, user.id, "invitation.accept", "user", user.id)
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise InvitationConflict("username already exists") from error
    return user


async def change_own_password(
    db: AsyncSession, user: User, current_password: str, new_password: str
) -> None:
    current_user = await require_system_resource_action(
        db, user, "account", "change_password", relation="own"
    )
    verified_password_hash = current_user.password_hash.hash_string
    if not await verify_password_async(current_user.password_hash, current_password):
        raise InvalidCredentials("Current password incorrect")
    try:
        password_hash = await hash_password_async(new_password)
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    current_user = await require_system_resource_action(
        db,
        current_user,
        "account",
        "change_password",
        relation="own",
        lock="write",
    )
    if not compare_digest(current_user.password_hash.hash_string, verified_password_hash):
        raise InvalidCredentials("Current password incorrect")
    current_user.password_hash = password_hash
    record_event(
        db,
        current_user.id,
        "account.password.changed",
        "user",
        current_user.id,
    )
    await db.commit()
