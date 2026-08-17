from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from quirebase.audit import record_event
from quirebase.core.crypto import generate_token, token_hash
from quirebase.core.errors import ResourceNotFound
from quirebase.models import LoginSession, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def create_login_session(
    db: Session, user: User, session_days: int = 30
) -> tuple[LoginSession, str]:
    raw = generate_token(32)
    login = LoginSession(
        token_hash=token_hash(raw),
        csrf_token=generate_token(24),
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=session_days),
    )
    db.add(login)
    db.commit()
    return login, raw


def get_login_session_by_token(db: Session, raw_token: str) -> LoginSession | None:
    if not raw_token:
        return None
    login = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(raw_token)))
    if (
        login is None
        or login.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)
        or not login.user.active
    ):
        return None
    return login


def list_user_sessions(db: Session, user_id: str) -> list[LoginSession]:
    return list(
        db.scalars(
            select(LoginSession)
            .where(LoginSession.user_id == user_id)
            .order_by(LoginSession.created_at.desc())
        ).all()
    )


def revoke_session(db: Session, user: User, session_id: str) -> None:
    target = db.get(LoginSession, session_id)
    if target is None or target.user_id != user.id:
        raise ResourceNotFound("session not found")
    record_event(db, user.id, "auth.session.revoke", "login_session", target.id)
    db.delete(target)
    db.commit()


def revoke_all_sessions(db: Session, user: User) -> int:
    count = (
        db.scalar(
            select(func.count()).select_from(LoginSession).where(LoginSession.user_id == user.id)
        )
        or 0
    )
    record_event(
        db,
        user.id,
        "auth.sessions.revoke_all",
        "user",
        user.id,
        detail={"revoked_sessions": count},
    )
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    db.commit()
    return count
