from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status

from quirebase.accounts.sessions import get_login_session_by_token
from quirebase.core.config import get_settings
from quirebase.core.crypto import compare_digest, token_hash
from quirebase.core.database import get_db
from quirebase.models import LoginSession, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def login_identity(request: Request, username: str) -> str:
    address = request.client.host if request.client else "unknown"
    return token_hash(f"{address}\0{username.casefold()}")


def current_login(request: Request, db: Session = Depends(get_db)) -> LoginSession:
    raw = request.cookies.get(get_settings().session_cookie)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    login = get_login_session_by_token(db, raw)
    if login is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return login


def current_user(login: LoginSession = Depends(current_login)) -> User:
    return login.user


def require_csrf(request: Request, login: LoginSession = Depends(current_login)) -> None:
    supplied = request.headers.get("x-csrf-token")
    if supplied is None:
        supplied = request.query_params.get("csrf_token")
    if not supplied or not compare_digest(supplied, login.csrf_token):
        raise HTTPException(status_code=403, detail="invalid CSRF token")
