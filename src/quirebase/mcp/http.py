from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from quirebase.mcp.auth import ApiTokenVerifier, SessionFactory
from quirebase.mcp.server import create_mcp_server
from quirebase.mcp.transport_security import McpOriginMiddleware, cors_origin_allowlist

if TYPE_CHECKING:
    from mcp.server import MCPServer
    from starlette.types import ASGIApp

    from quirebase.core.config import Settings


@dataclass(frozen=True)
class McpHttpMount:
    server: MCPServer
    app: ASGIApp


def create_mcp_http_mount(
    session_factory: SessionFactory,
    *,
    allowed_hosts: list[str],
    settings: Settings,
) -> McpHttpMount:
    """Build a Streamable HTTP mount protected by an expiring API Token."""
    verifier = ApiTokenVerifier(session_factory)
    server = create_mcp_server(session_factory=session_factory, settings=settings)
    transport_security = TransportSecuritySettings(
        # The outer middleware pair below replaces the SDK's narrower Host matcher
        # while preserving both Host and Origin DNS-rebinding defenses. The SDK
        # continues to validate POST media types when this flag is disabled.
        enable_dns_rebinding_protection=False,
    )
    protocol_app = server.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        transport_security=transport_security,
    )
    authenticated_app: ASGIApp = AuthenticationMiddleware(
        AuthContextMiddleware(RequireAuthMiddleware(protocol_app, required_scopes=[])),
        backend=BearerAuthBackend(verifier),
    )
    cors_origins, cors_origin_regex = cors_origin_allowlist(settings.mcp_allowed_origin_list)
    cors_app: ASGIApp = CORSMiddleware(
        authenticated_app,
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
    return McpHttpMount(server=server, app=protected_app)
