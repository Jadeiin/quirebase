from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from quirebase.accounts.sessions import get_login_session_by_token
from quirebase.core.config import get_settings
from quirebase.core.crypto import compare_digest_bytes, token_hash
from quirebase.core.database import get_db
from quirebase.models import LoginSession, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def login_identity(request: Request, username: str) -> str:
    address = request.client.host if request.client else "unknown"
    return token_hash(f"{address}\0{username.casefold()}")


async def current_login(request: Request, db: AsyncSession = Depends(get_db)) -> LoginSession:
    raw = request.cookies.get(get_settings().session_cookie)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    login = await get_login_session_by_token(db, raw)
    if login is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    request.state.csrf_token = login.csrf_token
    return login


def current_user(login: LoginSession = Depends(current_login)) -> User:
    return login.user


async def require_csrf(request: Request, login: LoginSession = Depends(current_login)) -> None:
    if request.method not in UNSAFE_METHODS:
        return
    supplied: Any = request.headers.get("x-csrf-token")
    if supplied is None:
        form = await request.form()
        supplied = form.get("csrf_token")
    if not isinstance(supplied, str) or not _matches(supplied, login.csrf_token):
        raise HTTPException(status_code=403, detail="invalid CSRF token")


def _matches(supplied: str, expected: str) -> bool:
    # Compare bytes so non-ASCII input is a mismatch instead of a TypeError.
    return compare_digest_bytes(supplied.encode("utf-8"), expected.encode("utf-8"))


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "administrator":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return user


def protected_router(**kwargs: Any) -> APIRouter:
    """Router policy for cookie-authenticated endpoints.

    Attaching ``require_csrf`` here covers every unsafe method by default, so a new
    mutation route cannot silently omit CSRF validation. ``require_csrf`` is a no-op
    for safe methods, and every route on a protected router already authenticates
    through ``current_login``, so the shared dependency is solved once per request.
    Pre-authentication mutations (``/login``, ``/accept-invitation/{token}``) live on
    explicit public routers instead; see tests/test_csrf.py for the route policy
    contract.
    """
    extra_dependencies = list(kwargs.pop("dependencies", []))
    return APIRouter(dependencies=[*extra_dependencies, Depends(require_csrf)], **kwargs)


def public_router(**kwargs: Any) -> APIRouter:
    """Router for endpoints reachable without a Login Session.

    Unsafe methods here are exempt from the session-bound CSRF policy and must be
    enumerated in tests/test_csrf.py.
    """
    return APIRouter(**kwargs)
