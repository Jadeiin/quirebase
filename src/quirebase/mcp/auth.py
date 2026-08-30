from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import anyio
from mcp.server.auth.provider import AccessToken

from quirebase.accounts import verify_api_token
from quirebase.core.database import SessionLocal

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from quirebase.accounts import VerifiedApiToken


class SessionFactory(Protocol):
    def __call__(self) -> Session: ...


class ApiTokenVerifier:
    """Adapt Accounts-owned opaque API Tokens to the MCP SDK's bearer verifier."""

    def __init__(self, session_factory: SessionFactory = SessionLocal):
        self._session_factory = session_factory

    async def verify_token(self, raw_token: str) -> AccessToken | None:
        verified = await anyio.to_thread.run_sync(self._verify, raw_token)
        if verified is None:
            return None
        return AccessToken(
            token="<redacted>",
            client_id=f"quirebase-api-token:{verified.token_id}",
            scopes=[],
            expires_at=int(verified.expires_at.timestamp()),
            subject=verified.user_id,
        )

    def _verify(self, raw_token: str) -> VerifiedApiToken | None:
        with self._session_factory() as db:
            return verify_api_token(db, raw_token)
