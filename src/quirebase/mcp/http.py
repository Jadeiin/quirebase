from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from quirebase.mcp.auth import ApiTokenVerifier, SessionFactory
from quirebase.mcp.server import create_mcp_server
from quirebase.mcp.transport_security import McpOriginMiddleware, cors_origin_allowlist

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from fastapi import FastAPI
    from fastmcp import FastMCP
    from starlette.types import ASGIApp

    from quirebase.core.config import Settings


@dataclass(frozen=True)
class McpHttpMount:
    server: FastMCP
    app: ASGIApp
    lifespan: Callable[[], Any]


def _internal_api_base_url(allowed_hosts: list[str]) -> str:
    """Choose a concrete host accepted by the outer app's TrustedHost policy."""
    host = allowed_hosts[0]
    if host == "*":
        host = "fastapi"
    elif host.startswith("*."):
        host = f"mcp-internal{host[1:]}"
    return f"http://{host}"


def create_mcp_http_mount(
    api_app: FastAPI,
    session_factory: SessionFactory,
    *,
    allowed_hosts: list[str],
    settings: Settings,
) -> McpHttpMount:
    """Generate and protect a stateless Streamable HTTP MCP projection of the API."""
    verifier = ApiTokenVerifier(session_factory)
    server = create_mcp_server(
        api_app,
        token_verifier=verifier,
        internal_base_url=_internal_api_base_url(allowed_hosts),
    )
    protocol_app = server.http_app(
        path="/",
        json_response=True,
        stateless_http=True,
        host_origin_protection=False,
    )
    cors_origins, cors_origin_regex = cors_origin_allowlist(settings.mcp_allowed_origin_list)
    cors_app: ASGIApp = CORSMiddleware(
        protocol_app,
        allow_origins=cors_origins,
        allow_origin_regex=cors_origin_regex,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Last-Event-ID",
            "MCP-Protocol-Version",
            "MCP-Session-Id",
        ],
        expose_headers=["MCP-Session-Id"],
    )
    origin_protected_app: ASGIApp = McpOriginMiddleware(
        cors_app,
        allowed_origins=settings.mcp_allowed_origin_list,
    )
    protected_app: ASGIApp = TrustedHostMiddleware(
        origin_protected_app,
        allowed_hosts=allowed_hosts,
    )

    @asynccontextmanager
    async def lifespan() -> AsyncIterator[None]:
        async with protocol_app.lifespan(protocol_app):
            yield

    return McpHttpMount(server=server, app=protected_app, lifespan=lifespan)
