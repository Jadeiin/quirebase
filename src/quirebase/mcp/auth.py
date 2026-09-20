from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from fastmcp.server.auth import AccessToken, TokenVerifier

from quirebase.accounts import verify_api_token
from quirebase.core.database import AsyncSessionLocal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SessionFactory(Protocol):
    def __call__(self) -> AsyncSession: ...


class ApiTokenVerifier(TokenVerifier):
    """Adapt Accounts-owned opaque API Tokens to FastMCP bearer authentication."""

    def __init__(self, session_factory: SessionFactory = AsyncSessionLocal):
        super().__init__()
        self._session_factory = session_factory

    async def verify_token(self, raw_token: str) -> AccessToken | None:
        async with self._session_factory() as db:
            verified = await verify_api_token(db, raw_token)
        if verified is None:
            return None
        client_id = f"quirebase-api-token:{verified.token_id}"
        return AccessToken(
            token="<redacted>",
            client_id=client_id,
            scopes=[],
            expires_at=int(verified.expires_at.timestamp()),
            subject=verified.user_id,
            claims={"api_token_id": verified.token_id},
        )
