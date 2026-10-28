---
title: Connect an MCP client
description: Use the curated research tool surface with a revocable API Token.
---

Quirebase exposes MCP Streamable HTTP at `/mcp/` on your application's origin.
Open **Account settings → API Tokens → Client connection guide** for the exact endpoint and a client configuration
example. Create a token there and configure your client to send it as a Bearer Authorization header.

MCP uses [API Tokens](/developers/http-api/#create-a-credential), not browser Login Session cookies.
The current server does not implement OAuth authorization discovery. Choose a client that supports
an explicitly configured endpoint and Bearer header.

## Discover tools and choose a Workspace

Clients initially see `search_tools`, `get_schema`, and `call_tool`:

1. Search with English keywords for the task you want to perform.
2. For an unfamiliar tool or complex input, retrieve its full contract with
   `get_schema(tools=["tool.name"], detail="full")`. Compact search summaries omit some constraints.
3. Begin with `workspaces.get_workspaces` to select an accessible Workspace ID.
4. Invoke the selected operation through `call_tool` using its full schema.
5. Review Import previews and diagnostics before explicit confirmation.

The curated surface includes ordinary research reads and mutations: Item metadata and organization,
Projects, document metadata, Annotations and Replies, Tags, Discussions, Identifier Import,
Discovery, and citations. Available tools execute the same HTTP operations and authorization rules.

Administrator operations, file bytes, and the currently unstructured PDF full text are excluded.
MCP does not give an agent additional Workspace permissions or a separate research-data identity.

## Browser clients

Native clients normally send no Origin. Browser-based MCP clients need the operator to configure
`QUIREBASE_MCP_ALLOWED_ORIGINS` for their trusted origins. See
[configuration](/administration/configuration/#browser-mcp-access).

For implementation decisions and the curated allowlist, see the repository's
[MCP architecture decision](https://github.com/Jadeiin/quirebase/blob/main/docs/adr/0004-research-intelligence-mcp-and-agent.md).
