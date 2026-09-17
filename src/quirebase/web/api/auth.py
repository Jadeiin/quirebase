from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import (  # ruff: ignore[typing-only-third-party-import] - FastAPI resolves this dependency at runtime
    AsyncSession,
)

from quirebase.accounts import get_login_session_by_token, resolve_api_token_user, verify_api_token
from quirebase.audit import (
    current_programmatic_invocation,
    identify_programmatic_invocation,
    programmatic_invocation,
)
from quirebase.core.config import get_settings
from quirebase.core.database import get_db
from quirebase.models import User

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


bearer = HTTPBearer(auto_error=False)


async def http_api_invocation(request: Request) -> AsyncIterator[None]:  # ruff: ignore[unused-async]
    """Bind a route name so business Audit Events can retain API provenance."""
    route = request.scope.get("route")
    operation = getattr(route, "name", "unknown")
    invocation = programmatic_invocation("http", operation)
    invocation.__enter__()  # ruff: ignore[unnecessary-dunder-call]
    try:
        yield
    finally:
        invocation.__exit__(None, None, None)


async def current_api_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncIterator[User]:
    """Authenticate with an API Token or a same-origin Login Session.

    An explicit Authorization header always selects programmatic authentication. It
    never falls back to a browser cookie, even when the supplied credential is bad.
    """
    authorization = request.headers.get("authorization")
    if authorization is not None:
        if credentials is None or credentials.scheme.casefold() != "bearer":
            raise _authentication_required()
        verified = await verify_api_token(db, credentials.credentials)
        if verified is None:
            raise _authentication_required()
        user = await resolve_api_token_user(db, verified.user_id)
        trusted_invocation = current_programmatic_invocation()
        if trusted_invocation is not None and trusted_invocation.protocol == "mcp":
            identify_programmatic_invocation(
                api_token_id=verified.token_id,
                client_id=trusted_invocation.client_id or "mcp",
            )
            yield user
            return
        route = request.scope.get("route")
        operation = getattr(route, "name", "unknown")
        invocation = programmatic_invocation("http", operation)
        invocation.__enter__()  # ruff: ignore[unnecessary-dunder-call]
        try:
            identify_programmatic_invocation(
                api_token_id=verified.token_id,
                client_id="http-api",
            )
            yield user
        finally:
            invocation.__exit__(None, None, None)
        return

    raw_session = request.cookies.get(get_settings().session_cookie, "")
    login = await get_login_session_by_token(db, raw_session)
    if login is None:
        raise _authentication_required()
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        require_same_origin(request)
    yield login.user


def _authentication_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _normalized_origin(value: str) -> tuple[str, str, int] | None:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    return (
        parsed.scheme,
        parsed.hostname.casefold(),
        port or (443 if parsed.scheme == "https" else 80),
    )


def require_same_origin(request: Request) -> None:
    supplied = request.headers.get("origin", "")
    expected = get_settings().external_origin or str(request.base_url).rstrip("/")
    expected_origin = _normalized_origin(expected)
    if expected_origin is None or _normalized_origin(supplied) != expected_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="origin does not match request origin",
        )
