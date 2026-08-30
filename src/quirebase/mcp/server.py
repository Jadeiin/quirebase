from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server import MCPServer

from quirebase.core.config import get_settings
from quirebase.core.database import SessionLocal
from quirebase.mcp.policy import ToolPolicy
from quirebase.mcp.runtime import (
    IdentityProvider,
    McpRuntime,
    RequestIdentity,
    api_token_request_identity,
)
from quirebase.mcp.tools.discovery import register_discovery_tools
from quirebase.mcp.tools.documents import register_document_tools
from quirebase.mcp.tools.library import register_library_tools
from quirebase.mcp.tools.organization import register_organization_tools
from quirebase.mcp.tools.projects import register_project_tools

if TYPE_CHECKING:
    from mcp.server.auth.provider import TokenVerifier

    from quirebase.core.config import Settings
    from quirebase.mcp.auth import SessionFactory


def create_mcp_server(
    *,
    identity_provider: IdentityProvider = api_token_request_identity,
    session_factory: SessionFactory = SessionLocal,
    token_verifier: TokenVerifier | None = None,
    settings: Settings | None = None,
) -> MCPServer:
    """Build the MCP adapter; a token verifier protects its HTTP transport."""
    runtime = McpRuntime(
        session_factory=session_factory,
        identity_provider=identity_provider,
        policy=ToolPolicy(),
    )
    server = MCPServer(
        name="Quirebase",
        description=(
            "Authenticated research-library tools. File bytes, full text, account "
            "administration, and site operations are not exposed."
        ),
        token_verifier=token_verifier,
    )
    register_library_tools(server, runtime)
    register_project_tools(server, runtime)
    register_document_tools(server, runtime)
    register_organization_tools(server, runtime)
    register_discovery_tools(server, runtime, settings or get_settings())
    return server


__all__ = ["RequestIdentity", "api_token_request_identity", "create_mcp_server"]
