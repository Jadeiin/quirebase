---
title: Connect and verify an MCP client
description: Configure Streamable HTTP with an API Token, discover tools, select a Workspace, and verify a read.
---

Use an MCP client that supports Streamable HTTP and a configured Bearer Authorization header.
Quirebase does not currently provide OAuth authorization discovery. The server uses the same current
User and Workspace authority as the HTTP API.

## 1. Create the connection

1. In the application, open **Account settings → API Tokens** and create a token for the client.
2. Expand **Client connection guide** and copy the installation's MCP endpoint/configuration example.
3. Add that endpoint and Bearer header in the client's MCP settings. For clients using an
   `mcpServers` JSON structure, the shape is:

   ```json
   {
     "mcpServers": {
       "quirebase": {
         "url": "http://127.0.0.1:9060/mcp/",
         "headers": {"Authorization": "Bearer YOUR_API_TOKEN"}
       }
     }
   }
   ```

4. Replace the example origin and token. A remote client needs a network-reachable application URL;
   its `127.0.0.1` refers to the client's own host.
5. Save/reconnect and inspect the tool list.

Client configuration formats differ; use the equivalent Streamable HTTP/header fields in your client.
Browser Login Session cookies are not MCP credentials, and query-string tokens are rejected.

## 2. Discover a tool and inspect its schema

**Check the connection:** the initial tool list contains `search_tools`, `get_schema`, and `call_tool`.
Search with English task keywords; for example, use `search_tools` with:

```json
{"query": "list accessible workspaces"}
```

For an unfamiliar tool, retrieve its full input/output schema before calling it:

```json
{"tools": ["workspaces.get_workspaces"], "detail": "full"}
```

Pass this to `get_schema`. Compact search summaries omit some constraints; reuse a schema you already
retrieved instead of guessing required arguments.

## 3. Select a Workspace and verify a read

Call the chosen tool through `call_tool`. To list accessible Workspaces:

```json
{"name": "workspaces.get_workspaces", "arguments": {}}
```

Choose a returned Workspace ID before requesting research content. Search for the task you want,
inspect its schema, and supply the required Workspace and resource IDs. A successful list proves
transport and token access; a research read additionally verifies that Workspace's current authority.

For Identifier Import, the sequence is preparation → preview and diagnostics → explicit confirmation.
Ask the User to review the prepared result before confirmation. An agent does not receive extra
permissions just because it can discover a tool.

## Know the tool boundary

The curated surface includes ordinary Item metadata/organization, Projects, document metadata,
Annotations/Replies, Tags, Discussions, Identifier Import, Discovery, and citations. Tools execute
the same HTTP operations. Administrator operations, file bytes, and the currently unstructured PDF
full text are excluded. API Tokens have no independent per-tool scopes.

## Resolve connection problems

| Symptom | Check |
| --- | --- |
| Cannot reach endpoint | Application origin, network access, TLS, and the client's Streamable HTTP support |
| 401 | Token expiration/revocation, exact Bearer header, active User |
| Connected but research denied | Explicit Workspace ID, active membership, and current resource authority |
| Browser client blocked by Origin/CORS | Operator's explicit `QUIREBASE_MCP_ALLOWED_ORIGINS` allowlist |

Native clients normally send no Origin. Browser MCP CORS is separate from HTTP API and S3 CORS.
See [configuration](/administration/configuration/#browser-mcp-access). Implementation choices live
in the [MCP ADR](https://github.com/Jadeiin/quirebase/blob/main/docs/adr/0004-research-intelligence-mcp-and-agent.md).
