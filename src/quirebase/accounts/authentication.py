from __future__ import annotations

import json
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
from quirebase.core.crypto import hash_password, token_hash, verify_password
from quirebase.core.errors import DomainError, ResourceNotFound, ValidationFailure
from quirebase.models import AuditEvent, Invitation, LoginSession, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class AuthenticationFailure(DomainError):
    pass


class InvalidCredentials(AuthenticationFailure):
    pass


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
        db.add(
            AuditEvent(
                actor_id=None,
                action="auth.login.throttled",
                target_type="user",
                target_id=None,
                detail=json.dumps({"identity_hash": identity}),
            )
        )
        db.commit()
        raise

    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.active or not verify_password(user.password_hash, password):
        record_login_failure(db, identity)
        db.add(
            AuditEvent(
                actor_id=None,
                action="auth.login.failed",
                target_type="user",
                target_id=user.id if user else None,
                detail=json.dumps({"identity_hash": identity}),
            )
        )
        db.commit()
        raise InvalidCredentials("Invalid credentials")

    clear_login_failures(db, identity)
    login_session, raw = create_login_session(db, user, session_days=session_days)
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="auth.login.succeeded",
            target_type="login_session",
            target_id=login_session.id,
            detail=json.dumps({"identity_hash": identity}),
        )
    )
    db.commit()
    return login_session, raw


def logout(db: Session, user: User, login_session: LoginSession) -> None:
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="auth.logout",
            target_type="login_session",
            target_id=login_session.id,
        )
    )
    db.delete(login_session)
    db.commit()


def accept_invitation(db: Session, token: str, password: str) -> User:
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == token_hash(token)))
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)
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
    db.add(
        AuditEvent(
            actor_id=user.id, action="invitation.accept", target_type="user", target_id=user.id
        )
    )
    db.commit()
    return user
