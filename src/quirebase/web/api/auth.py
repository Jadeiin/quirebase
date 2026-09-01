from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import (  # ruff: ignore[typing-only-third-party-import] - FastAPI resolves this dependency at runtime
    AsyncSession,
)

from quirebase.accounts import resolve_api_token_user, verify_api_token
from quirebase.audit import identify_programmatic_invocation, programmatic_invocation
from quirebase.core.database import get_db
from quirebase.models import User

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


bearer = HTTPBearer(auto_error=False)


async def http_api_invocation(request: Request) -> AsyncIterator[None]:  # ruff: ignore[unused-async]
    """Bind a route name so business Audit Events can retain API provenance."""
    route = request.scope.get("route")
    operation = getattr(route, "name", "unknown")
    with programmatic_invocation("http", operation):
        yield


async def current_api_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Authenticate the HTTP API exclusively with an Accounts-owned API Token."""
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    verified = await verify_api_token(db, credentials.credentials)
    if verified is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    identify_programmatic_invocation(
        api_token_id=verified.token_id,
        client_id="http-api",
    )
    return await resolve_api_token_user(db, verified.user_id)
