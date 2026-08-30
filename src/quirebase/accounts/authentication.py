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
from quirebase.core.crypto import hash_password, token_hash, verify_password
from quirebase.core.errors import DomainError, ResourceNotFound, ValidationFailure
from quirebase.core.timezones import as_utc
from quirebase.models import Invitation, LoginSession, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class AuthenticationFailure(DomainError):
    pass


class InvalidCredentials(AuthenticationFailure):
    pass


def resolve_api_token_user(db: Session, subject: str) -> User:
    """Resolve a verified API Token subject to an active local User."""
    user = db.get(User, subject)
    if user is None or not user.active:
        raise AuthenticationFailure("access token subject is not an active user")
    return user


def authenticate_user(
    db: Session,
    identity: str,
    username: str,
    password: str,
    session_days: int = 30,
) -> tuple[LoginSession, str]:
    try:
        check_login_throttle(db, identity)
    except LoginThrottled:
        record_event(
            db,
            None,
            "auth.login.throttled",
            "user",
            detail={"identity_hash": identity},
        )
        db.commit()
        raise

    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.active or not verify_password(user.password_hash, password):
        record_login_failure(db, identity)
        record_event(
            db,
            None,
            "auth.login.failed",
            "user",
            user.id if user else None,
            detail={"identity_hash": identity},
        )
        db.commit()
        raise InvalidCredentials("Invalid credentials")

    clear_login_failures(db, identity)
    login_session, raw = create_login_session(db, user, session_days=session_days)
    record_event(
        db,
        user.id,
        "auth.login.succeeded",
        "login_session",
        login_session.id,
        detail={"identity_hash": identity},
    )
    db.commit()
    return login_session, raw


def logout(db: Session, user: User, login_session: LoginSession) -> None:
    record_event(db, user.id, "auth.logout", "login_session", login_session.id)
    db.delete(login_session)
    db.commit()


def accept_invitation(db: Session, token: str, password: str) -> User:
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == token_hash(token)))
    if (
        invitation is None
        or invitation.accepted_at is not None
        or as_utc(invitation.expires_at) <= datetime.now(UTC)
    ):
        raise ResourceNotFound("invitation not found or expired")
    if db.scalar(select(User).where(User.username == invitation.username)):
        raise InvitationConflict("username already exists")
    try:
        encoded = hash_password(password)
    except ValueError as error:
        raise ValidationFailure(str(error)) from error

    user = User(username=invitation.username, password_hash=encoded, role=invitation.role)
    db.add(user)
    invitation.accepted_at = datetime.now(UTC)
    db.flush()
    record_event(db, user.id, "invitation.accept", "user", user.id)
    db.commit()
    return user


def change_own_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(user.password_hash, current_password):
        raise InvalidCredentials("Current password incorrect")
    try:
        user.password_hash = hash_password(new_password)
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    record_event(db, user.id, "account.password.changed", "user", user.id)
    db.commit()
