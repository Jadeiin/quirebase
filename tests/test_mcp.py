from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx2
import pytest
from fastmcp import Client
from sqlalchemy import select

from quirebase.accounts import create_api_token
from quirebase.core.database import get_db
from quirebase.mcp import TOOL_ALLOWLIST
from quirebase.models import AuditEvent, Item, User
from quirebase.web.app import create_app

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def mcp_client(factory):
    app = create_app(mcp_session_factory=factory)

    async def override_db():
        session = factory()
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_db] = override_db
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        yield client, app


@asynccontextmanager
async def fastmcp_client(factory):
    app = create_app(mcp_session_factory=factory)

    async def override_db():
        session = factory()
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_db] = override_db
    async with app.router.lifespan_context(app), Client(app.state.mcp_server) as client:
        yield client, app


def _headers(raw_token: str) -> dict[str, str]:
    return {
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {raw_token}",
        "Content-Type": "application/json",
    }


async def test_fastmcp_client_lists_the_tool_search_surface(async_session_factory):
    async with fastmcp_client(async_session_factory) as (client, _app):
        tools = await client.list_tools()

    assert {tool.name for tool in tools} == {"search_tools", "call_tool"}


async def _call(client, raw_token: str, name: str, arguments: dict, request_id: int = 1):
    return await client.post(
        "/mcp/",
        headers=_headers(raw_token),
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )


async def test_generated_tools_match_the_fixed_allowlist_and_annotations(async_session_factory):
    async with mcp_client(async_session_factory) as (_client, app):
        server = app.state.mcp_server
        tools = await server.list_tools()
        generated = {name: await server.get_tool(name) for name in TOOL_ALLOWLIST}

    assert {tool.name for tool in tools} == {"search_tools", "call_tool"}
    assert all(tool is not None for tool in generated.values())
    assert not any(name.startswith("admin.") for name in TOOL_ALLOWLIST)
    assert not any(
        "session" in name or "content" in name or "upload" in name for name in TOOL_ALLOWLIST
    )
    annotations = {name: tool.annotations for name, tool in generated.items()}
    assert annotations["discovery.search_discovery"].open_world_hint is True
    assert annotations["documents.list_documents"].read_only_hint is True
    assert annotations["annotations.delete_annotation"].destructive_hint is True
    assert annotations["annotations.delete_reply"].destructive_hint is True


async def test_tool_search_discovers_curated_tools(async_session_factory):
    async with mcp_client(async_session_factory) as (_client, app):
        result = await app.state.mcp_server.call_tool(
            "search_tools", {"query": "update project"}, run_middleware=False
        )

    assert result.is_error is False
    matches = json.loads(result.content[0].text)
    matching_tool = next(tool for tool in matches if tool["name"] == "projects.update_project")
    assert set(matching_tool["inputSchema"]["properties"]) == {
        "project_id",
        "name",
        "description",
        "visibility",
    }


async def test_generated_tool_schemas_come_from_the_api_contract(async_session_factory):
    async with mcp_client(async_session_factory) as (_client, app):
        server = app.state.mcp_server
        tools = {name: await server.get_tool(name) for name in TOOL_ALLOWLIST}

    assert set(tools["library.search_items"].parameters["properties"]) == {
        "query",
        "tag",
        "project",
        "year",
        "keyword",
        "author",
        "page",
    }
    assert set(tools["projects.update_project"].parameters["properties"]) == {
        "project_id",
        "name",
        "description",
        "visibility",
    }
    assert set(tools["annotations.update_annotation"].parameters["properties"]) == {
        "item_id",
        "annotation_id",
        "version",
        "page_index",
        "kind",
        "payload",
        "scope",
        "project_id",
        "body",
        "selected_text",
    }


async def test_generated_library_tool_calls_api_and_preserves_mcp_audit_provenance(
    async_db, async_session_factory
):
    user = User(username="generated-mcp-writer", password_hash="unused")
    async_db.add(user)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Generated MCP", expires_in_days=30)

    async with mcp_client(async_session_factory) as (client, _app):
        response = await _call(
            client,
            grant.raw_token,
            "library.create_library_item",
            {"title": "Created through generated MCP", "doi": "10.1/generated"},
        )

    assert response.status_code == 200
    payload = response.json()["result"]
    assert payload["isError"] is False
    item_id = payload["structuredContent"]["id"]
    item = await async_db.get(Item, item_id)
    assert item is not None
    assert item.created_by == user.id
    event = await async_db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "item.create", AuditEvent.target_id == item_id
        )
    )
    assert event is not None
    assert json.loads(event.detail) == {
        "invocation": {
            "protocol": "mcp",
            "operation": "library.create_library_item",
            "api_token_id": grant.token_id,
            "client_id": f"quirebase-api-token:{grant.token_id}",
        }
    }


async def test_tool_search_proxy_calls_the_curated_tool(async_db, async_session_factory):
    user = User(username="tool-search-writer", password_hash="unused")
    async_db.add(user)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Tool search", expires_in_days=30)

    async with mcp_client(async_session_factory) as (client, _app):
        discovered = await _call(
            client,
            grant.raw_token,
            "search_tools",
            {"query": "create bibliographic item"},
        )
        created = await _call(
            client,
            grant.raw_token,
            "call_tool",
            {
                "name": "library.create_library_item",
                "arguments": {"title": "Created through tool search"},
            },
        )

    assert discovered.status_code == 200
    discovered_tools = json.loads(discovered.json()["result"]["content"][0]["text"])
    assert any(tool["name"] == "library.create_library_item" for tool in discovered_tools)
    assert created.status_code == 200
    created_result = created.json()["result"]
    assert created_result["isError"] is False
    item_id = created_result["structuredContent"]["id"]
    event = await async_db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "item.create", AuditEvent.target_id == item_id
        )
    )
    assert event is not None
    assert json.loads(event.detail)["invocation"]["operation"] == "library.create_library_item"


async def test_generated_tool_returns_api_version_conflict_as_mcp_error(
    async_db, async_session_factory
):
    user = User(username="generated-mcp-conflict", password_hash="unused")
    async_db.add(user)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Generated MCP conflict", expires_in_days=30)

    async with mcp_client(async_session_factory) as (client, _app):
        created = await _call(
            client,
            grant.raw_token,
            "library.create_library_item",
            {"title": "Versioned Item"},
        )
        item_id = created.json()["result"]["structuredContent"]["id"]
        arguments = {
            "item_id": item_id,
            "expected_version": 1,
            "metadata": {"title": "First update"},
        }
        first = await _call(client, grant.raw_token, "library.update_library_item", arguments, 2)
        conflict = await _call(client, grant.raw_token, "library.update_library_item", arguments, 3)

    assert first.json()["result"]["isError"] is False
    conflict_result = conflict.json()["result"]
    assert conflict_result["isError"] is True
    assert "409" in conflict_result["content"][0]["text"]
    assert "version" in conflict_result["content"][0]["text"].casefold()


async def test_generated_tool_does_not_fall_back_to_cookie_auth(async_db, async_session_factory):
    user = User(username="generated-mcp-auth", password_hash="unused")
    async_db.add(user)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Generated MCP auth", expires_in_days=30)

    async with mcp_client(async_session_factory) as (client, _app):
        client.cookies.set("quirebase_session", grant.raw_token)
        missing = await client.post(
            "/mcp/",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "library.search_items", "arguments": {}},
            },
        )
        invalid = await _call(client, "invalid", "library.search_items", {})

    assert missing.status_code == 401
    assert invalid.status_code == 401
