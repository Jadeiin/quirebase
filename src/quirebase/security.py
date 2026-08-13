from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import LoginSession, LoginThrottle, User

password_hasher = PasswordHasher()
THROTTLE_WINDOW = timedelta(minutes=15)
THROTTLE_LIMIT = 5


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    return password_hasher.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login_identity(request: Request, username: str) -> str:
    address = request.client.host if request.client else "unknown"
    return token_hash(f"{address}\0{username.casefold()}")


def check_login_throttle(db: Session, identity: str) -> None:
    row = db.get(LoginThrottle, identity)
    if row is None:
        return
    started = row.window_started_at.replace(tzinfo=UTC)
    if started + THROTTLE_WINDOW <= datetime.now(UTC):
        db.delete(row)
        db.commit()
    elif row.failures >= THROTTLE_LIMIT:
        raise HTTPException(status_code=429, detail="too many login attempts; try again later")


def record_login_failure(db: Session, identity: str) -> None:
    row = db.get(LoginThrottle, identity)
    if row is None:
        row = LoginThrottle(identity_hash=identity, failures=1)
        db.add(row)
    else:
        row.failures += 1
    db.commit()


def clear_login_failures(db: Session, identity: str) -> None:
    row = db.get(LoginThrottle, identity)
    if row:
        db.delete(row)
        db.commit()


def create_login_session(db: Session, user: User) -> tuple[LoginSession, str]:
    raw = secrets.token_urlsafe(32)
    settings = get_settings()
    login = LoginSession(
        token_hash=token_hash(raw),
        csrf_token=secrets.token_urlsafe(24),
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=settings.session_days),
    )
    db.add(login)
    db.commit()
    return login, raw


def current_login(request: Request, db: Session = Depends(get_db)) -> LoginSession:
    raw = request.cookies.get(get_settings().session_cookie)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    login = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(raw)))
    if (
        login is None
        or login.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)
        or not login.user.active
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return login


def current_user(login: LoginSession = Depends(current_login)) -> User:
    return login.user


def require_csrf(request: Request, login: LoginSession = Depends(current_login)) -> None:
    supplied = request.headers.get("x-csrf-token")
    if supplied is None:
        supplied = request.query_params.get("csrf_token")
    if not supplied or not secrets.compare_digest(supplied, login.csrf_token):
        raise HTTPException(status_code=403, detail="invalid CSRF token")
