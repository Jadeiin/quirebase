from __future__ import annotations

import re
from typing import TYPE_CHECKING

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


def _origin_allowed(origin: str, allowed_origins: tuple[str, ...]) -> bool:
    if origin in allowed_origins:
        return True
    for allowed in allowed_origins:
        if not allowed.endswith(":*"):
            continue
        base = allowed[:-2]
        if origin.startswith(f"{base}:") and origin.removeprefix(f"{base}:").isdigit():
            return True
    return False


def cors_origin_allowlist(allowed_origins: list[str]) -> tuple[list[str], str | None]:
    """Translate the MCP origin policy into Starlette CORS settings."""
    exact_origins: list[str] = []
    wildcard_patterns: list[str] = []
    for origin in (value.strip() for value in allowed_origins):
        if not origin:
            continue
        if origin.endswith(":*"):
            wildcard_patterns.append(rf"{re.escape(origin[:-2])}:\d+")
        else:
            exact_origins.append(origin)
    origin_regex = rf"(?:{'|'.join(wildcard_patterns)})" if wildcard_patterns else None
    return exact_origins, origin_regex


class McpOriginMiddleware:
    """Reject browser Origins unless the deployment explicitly allows them."""

    def __init__(self, app: ASGIApp, *, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = tuple(origin.strip() for origin in allowed_origins if origin.strip())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            origin = Headers(scope=scope).get("origin")
            if origin is not None and not _origin_allowed(origin, self.allowed_origins):
                response = PlainTextResponse("Invalid Origin header", status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
