from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import httpx2
from fastmcp import FastMCP
from fastmcp.experimental.transforms.code_mode import GetSchemas
from fastmcp.server.dependencies import get_access_token, get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.providers.openapi import MCPType
from fastmcp.server.transforms.search import (
    BM25SearchTransform,
    serialize_tools_for_output_markdown,
)
from fastmcp.utilities.json_schema import compress_schema
from mcp.types import ToolAnnotations

from quirebase.audit import programmatic_invocation
from quirebase.mcp.policy import MCP_TOOLS, ToolEffect

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastmcp.server.auth import AccessToken, TokenVerifier
    from fastmcp.tools import ToolResult
    from fastmcp.utilities.openapi import HTTPRoute
    from mcp import types as mcp_types


class McpInvocationMiddleware(Middleware):
    """Bind trusted MCP provenance while a generated tool calls the API in-process."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mcp_types.CallToolRequestParams],
        call_next: CallNext[mcp_types.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        access_token = cast("AccessToken", get_access_token())
        with programmatic_invocation(
            "mcp",
            context.message.name,
            api_token_id=access_token.claims["api_token_id"],
            client_id=access_token.client_id,
        ):
            return await call_next(context)


class ForwardVerifiedBearerAuth(httpx2.Auth):
    """Forward the already-verified MCP bearer to the in-process API client."""

    def auth_flow(self, request: httpx2.Request):
        request.headers["authorization"] = get_http_headers(include={"authorization"})[
            "authorization"
        ]
        yield request


def _route_type(route: HTTPRoute, _default: MCPType) -> MCPType:
    if route.operation_id in MCP_TOOLS:
        return MCPType.TOOL
    return MCPType.EXCLUDE


def _tool_annotations(effect: ToolEffect) -> ToolAnnotations:
    return ToolAnnotations(
        read_only_hint=effect in {ToolEffect.READ, ToolEffect.OPEN_WORLD_READ},
        destructive_hint=effect is ToolEffect.DESTRUCTIVE,
        idempotent_hint=effect
        in {ToolEffect.READ, ToolEffect.DESTRUCTIVE, ToolEffect.OPEN_WORLD_READ},
        open_world_hint=effect in {ToolEffect.OPEN_WORLD_READ, ToolEffect.OPEN_WORLD_WRITE},
    )


def _customize_component(route: HTTPRoute, component: Any) -> None:
    definition = MCP_TOOLS[cast("str", route.operation_id)]
    component.name = definition.name
    component.description = definition.description
    component.annotations = _tool_annotations(definition.effect)
    component.parameters = compress_schema(component.parameters, prune_titles=True)
    if component.output_schema is not None:
        component.output_schema = compress_schema(component.output_schema, prune_titles=True)


def create_mcp_server(
    api_app: FastAPI, *, token_verifier: TokenVerifier, internal_base_url: str
) -> FastMCP:
    """Generate the curated MCP surface from the canonical FastAPI OpenAPI contract."""
    server = FastMCP.from_fastapi(
        app=api_app,
        name="Quirebase",
        httpx_client_kwargs={
            "base_url": internal_base_url,
            "auth": ForwardVerifiedBearerAuth(),
        },
        route_map_fn=_route_type,
        mcp_component_fn=_customize_component,
        auth=token_verifier,
        middleware=[McpInvocationMiddleware()],
        dereference_schemas=False,
        instructions=(
            "Authenticated research-library tools. Translate tool-search queries into English "
            "keywords for search_tools. Search results are compact summaries that omit parameter "
            "constraints and safety annotations. For an unfamiliar tool or complex input, use "
            "get_schema with the selected tool names and detail='full' to inspect the complete "
            "contract before invoking it. Reuse schemas already retrieved; "
            "only fetch the tools you intend to use. "
            "Start with workspaces.get_workspaces to choose an accessible workspace_id; "
            "use that explicit Workspace for subsequent calls and inspect its authorization. "
            "Invoke selected tools through call_tool. "
            "Query discovery.discovery_providers and tools.citation_styles for available choices. "
            "Stage identifier imports, show the User the preview and diagnostics, and call "
            "imports.commit_staged_import only after their explicit confirmation. "
            "Use items.item_organize to inspect assigned Tags and Projects before and after edits. "
            "File bytes, full text, account administration, and site operations are not exposed."
        ),
    )
    search = BM25SearchTransform(
        max_results=5,
        always_visible=["get_schema"],
        search_result_serializer=serialize_tools_for_output_markdown,
    )
    server.add_tool(GetSchemas(default_detail="full")(search.get_tool_catalog))
    server.add_transform(search)
    return server


__all__ = ["create_mcp_server"]
