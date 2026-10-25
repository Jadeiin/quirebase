from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import httpx2
import pytest
from advanced_alchemy.types import FileObject
from app_helpers import json_payload
from fastmcp import Client
from inquiro import ProviderConfig, ProviderRuntime
from inquiro.transport import MockExchange, TransportResponse
from sqlalchemy import select
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.accounts import create_api_token
from quirebase.core.database import get_db
from quirebase.mcp import TOOL_ALLOWLIST
from quirebase.models import (
    AuditEvent,
    CitationStyle,
    FileRevision,
    Item,
    User,
    WorkspaceMember,
    WorkspaceRole,
)
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

    assert {tool.name for tool in tools} == {"search_tools", "get_schema", "call_tool"}


async def _call(client, raw_token: str, name: str, arguments: dict, request_id: int = 1):
    return await client.post(
        "/mcp/",
        headers=_headers(raw_token),
        json=json_payload({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }),
    )


async def _tool(client, raw_token: str, tool_name: str, **arguments):
    response = await _call(
        client,
        raw_token,
        "call_tool",
        {"name": tool_name, "arguments": arguments},
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False, result
    return result["structuredContent"]


async def _schemas(client, raw_token: str, *tool_names: str):
    response = await _call(client, raw_token, "get_schema", {"tools": list(tool_names)})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


async def test_token_client_discovers_its_workspace_before_searching(
    async_db, async_session_factory
):
    user = User(username="workspace-mcp-reader", password_hash="unused")
    outsider = User(username="workspace-mcp-outsider", password_hash="unused")
    async_db.add_all([user, outsider])
    await async_db.flush()
    await provision_initial_workspace(async_db, user)
    other_workspace = await provision_initial_workspace(async_db, outsider)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Workspace discovery", expires_in_days=30)

    async with mcp_client(async_session_factory) as (client, _app):
        discovered = await _call(
            client, grant.raw_token, "search_tools", {"query": "list accessible workspaces"}
        )
        summary = discovered.json()["result"]["content"][0]["text"]
        assert "### workspaces.get_workspaces" in summary
        (entry,) = await _schemas(client, grant.raw_token, "workspaces.get_workspaces")
        assert "workspace_id" not in entry["inputSchema"].get("required", [])
        workspaces = await _tool(client, grant.raw_token, entry["name"])
        assert workspaces["total"] == 1
        workspace_id = workspaces["items"][0]["id"]
        workspace = await _tool(
            client, grant.raw_token, "workspaces.get_user_workspace", workspace_id=workspace_id
        )
        assert workspace["current_role"] == "owner"
        members = await _tool(
            client, grant.raw_token, "workspaces.get_workspace_members", workspace_id=workspace_id
        )
        assert [member["username"] for member in members["items"]] == [user.username]
        items = await _tool(
            client, grant.raw_token, "library.search_items", workspace_id=workspace_id
        )
        assert items["items"] == []
        denied = await _call(
            client,
            grant.raw_token,
            "workspaces.get_user_workspace",
            {"workspace_id": other_workspace.id},
        )
        assert denied.json()["result"]["isError"] is True


async def test_identifier_import_can_be_reviewed_confirmed_and_replayed_through_mcp(
    async_db, async_session_factory, monkeypatch
):
    user = User(username="mcp-importer", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    await provision_initial_workspace(async_db, user)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Identifier import", expires_in_days=30)

    def respond(request):
        assert "api.crossref.org" in request.url
        assert not any(key.casefold() == "authorization" for key in (request.headers or {}))
        if request.url.endswith("missing"):
            return TransportResponse(404)
        return TransportResponse(
            200,
            json.dumps({
                "message": {
                    "DOI": "10.1234/mcp-study",
                    "title": ["Reviewed MCP import"],
                    "type": "journal-article",
                }
            }).encode(),
        )

    exchange = MockExchange(respond)
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )

    async with mcp_client(async_session_factory) as (client, _app):
        workspaces = await _tool(client, grant.raw_token, "workspaces.get_workspaces")
        workspace_id = workspaces["items"][0]["id"]
        context = {"workspace_id": workspace_id}
        providers = await _tool(client, grant.raw_token, "discovery.discovery_providers", **context)
        assert "crossref" in {provider["id"] for provider in providers["lookup"]}
        preview = await _tool(
            client,
            grant.raw_token,
            "imports.stage_identifiers_import",
            **context,
            identifiers=["10.1234/mcp-study", "10.1234/missing"],
            provider="crossref",
        )
        assert preview["committed_item_ids"] == []
        assert preview["records"][0]["metadata"]["title"] == "Reviewed MCP import"
        assert preview["errors"][0]["code"] == "metadata_not_found"
        assert (await _tool(client, grant.raw_token, "library.search_items", **context))[
            "total"
        ] == 0
        batches = await _tool(client, grant.raw_token, "imports.import_batches", **context)
        assert [batch["id"] for batch in batches["items"]] == [preview["id"]]
        batch_context = context | {"batch_id": preview["id"]}
        assert (
            await _tool(client, grant.raw_token, "imports.import_batch", **batch_context) == preview
        )

        receipt = await _tool(
            client, grant.raw_token, "imports.commit_staged_import", **batch_context
        )
        assert receipt["status"] == "committed"
        assert len(receipt["committed_item_ids"]) == 1
        replay = await _tool(
            client, grant.raw_token, "imports.commit_staged_import", **batch_context
        )
        assert replay == receipt
        items = await _tool(
            client, grant.raw_token, "library.search_items", **context, import_batch=preview["id"]
        )
        assert [item["id"] for item in items["items"]] == receipt["committed_item_ids"]
        await _tool(client, grant.raw_token, "imports.delete_import", **batch_context)
        items = await _tool(client, grant.raw_token, "library.search_items", **context)
        assert [item["id"] for item in items["items"]] == receipt["committed_item_ids"]

    events = list(
        await async_db.scalars(
            select(AuditEvent).where(
                AuditEvent.action.in_(["metadata.import.preview", "bibliography.import"])
            )
        )
    )
    assert len(events) == 2
    assert {event.detail["invocation"]["operation"] for event in events} == {
        "imports.stage_identifiers_import",
        "imports.commit_staged_import",
    }
    assert all(
        event.detail["invocation"]["api_token_id"] == str(grant.token_id) for event in events
    )


async def test_project_participant_can_join_organize_an_item_and_leave_through_mcp(
    async_db, async_session_factory
):
    owner = User(username="mcp-project-owner", password_hash="unused")
    editor = User(username="mcp-project-editor", password_hash="unused")
    async_db.add_all([owner, editor])
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, owner)
    async_db.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=editor.id, role=WorkspaceRole.editor)
    )
    await async_db.commit()
    owner_grant = await create_api_token(async_db, owner, "Project owner", expires_in_days=30)
    grant = await create_api_token(async_db, editor, "Project editor", expires_in_days=30)
    context = {"workspace_id": workspace.id}

    async with mcp_client(async_session_factory) as (client, _app):
        project = await _tool(
            client,
            owner_grant.raw_token,
            "projects.create_user_project",
            **context,
            name="Reading group",
            participation="open",
        )
        project_context = context | {"project_id": project["id"]}
        joinable = await _tool(
            client, grant.raw_token, "projects.list_projects", **context, view="joinable"
        )
        assert [row["id"] for row in joinable["items"]] == [project["id"]]
        await _tool(client, grant.raw_token, "projects.join_project_api", **project_context)
        detail = await _tool(client, grant.raw_token, "projects.get_project", **project_context)
        assert detail["is_participating"] is True
        item = await _tool(
            client,
            grant.raw_token,
            "library.create_library_item",
            **context,
            metadata={
                "id": "https://doi.org/10.1234/reading-group",
                "type": "Document",
                "title": "Reading group Item",
            },
        )
        item_context = context | {"item_id": item["id"]}
        before = await _tool(client, grant.raw_token, "items.item_organize", **item_context)
        assert before["tag_matrix"]["assigned_ids"] == []
        assert not next(row for row in before["projects"] if row["id"] == project["id"])["assigned"]
        tag = await _tool(
            client, grant.raw_token, "library.add_item_tag", **item_context, name="To read"
        )
        await _tool(
            client,
            grant.raw_token,
            "projects.add_project_item",
            **project_context,
            item_id=item["id"],
        )
        after = await _tool(client, grant.raw_token, "items.item_organize", **item_context)
        assert after["tag_matrix"]["assigned_ids"] == [tag["id"]]
        assert next(row for row in after["projects"] if row["id"] == project["id"])["assigned"]
        items = await _tool(
            client, grant.raw_token, "library.search_items", **context, project=project["id"]
        )
        assert [row["id"] for row in items["items"]] == [item["id"]]
        await _tool(client, grant.raw_token, "projects.leave_project_api", **project_context)
        detail = await _tool(client, grant.raw_token, "projects.get_project", **project_context)
        assert detail["is_participating"] is False
        assert (await _tool(client, grant.raw_token, "library.get_library_item", **item_context))[
            "id"
        ] == item["id"]


async def test_workspace_citation_style_can_be_discovered_and_used_through_mcp(
    async_db, async_session_factory
):
    user = User(username="mcp-style-reader", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, user)
    async_db.add(
        CitationStyle(
            workspace_id=workspace.id,
            created_by=user.id,
            name="Title only",
            csl_xml="""<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0" class="in-text">
              <info><title>Title only</title><id>https://example.test/title</id>
                <updated>2026-10-24T00:00:00Z</updated></info>
              <citation><layout><text variable="title"/></layout></citation>
              <bibliography><layout><text variable="title"/></layout></bibliography>
            </style>""",
        )
    )
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Citation styles", expires_in_days=30)
    context = {"workspace_id": workspace.id}

    async with mcp_client(async_session_factory) as (client, _app):
        styles = await _tool(
            client, grant.raw_token, "tools.citation_styles", **context, scope="custom"
        )
        assert styles["total"] == 1
        style = styles["items"][0]
        assert style["name"] == "Title only"
        item = await _tool(
            client,
            grant.raw_token,
            "library.create_library_item",
            **context,
            metadata={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Citable Item"},
        )
        citation = await _tool(
            client,
            grant.raw_token,
            "library.format_item_citation",
            **context,
            item_id=item["id"],
            style=style["key"],
        )
        assert "Citable Item" in citation["content"]


async def test_tags_and_duplicate_items_can_be_cleaned_up_through_mcp(
    async_db, async_session_factory
):
    user = User(username="mcp-library-maintainer", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, user)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Library cleanup", expires_in_days=30)
    context = {"workspace_id": workspace.id}
    metadata = {
        "id": "https://doi.org/10.1234/duplicate",
        "type": "Document",
        "title": "Duplicate candidate",
    }

    async with mcp_client(async_session_factory) as (client, _app):
        original = await _tool(
            client, grant.raw_token, "library.create_library_item", **context, metadata=metadata
        )
        duplicate = await _tool(
            client, grant.raw_token, "library.create_library_item", **context, metadata=metadata
        )
        duplicates = await _tool(
            client, grant.raw_token, "tools.duplicate_items", **context, mode="identifier"
        )
        assert {row["id"] for row in duplicates["groups"][0]} == {
            original["id"],
            duplicate["id"],
        }
        item_context = context | {"item_id": original["id"]}
        source = await _tool(
            client, grant.raw_token, "library.add_item_tag", **item_context, name="To read"
        )
        target = await _tool(
            client, grant.raw_token, "library.add_item_tag", **item_context, name="Reading"
        )
        await _tool(
            client,
            grant.raw_token,
            "tools.rename_user_tag",
            **context,
            tag_id=target["id"],
            name="Read next",
        )
        await _tool(
            client,
            grant.raw_token,
            "tools.merge_user_tags",
            **context,
            source_tag_id=source["id"],
            target_tag_id=target["id"],
        )
        tags = await _tool(client, grant.raw_token, "library.list_tags", **context)
        assert [(tag["id"], tag["name"]) for tag in tags["items"]] == [(target["id"], "Read next")]
        organized = await _tool(client, grant.raw_token, "items.item_organize", **item_context)
        assert organized["tag_matrix"]["assigned_ids"] == [target["id"]]
        await _tool(
            client, grant.raw_token, "tools.delete_user_tag", **context, tag_id=target["id"]
        )
        await _tool(
            client, grant.raw_token, "items.delete_library_item", **context, item_id=duplicate["id"]
        )
        remaining = await _tool(client, grant.raw_token, "library.search_items", **context)
        assert [row["id"] for row in remaining["items"]] == [original["id"]]
        assert (await _tool(client, grant.raw_token, "library.list_tags", **context))["total"] == 0


async def test_deleted_annotations_and_replies_can_be_restored_through_mcp(
    async_db, async_session_factory
):
    user = User(username="mcp-annotation-restorer", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, user)
    item = Item(
        workspace_id=workspace.id,
        created_by=user.id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Annotated Item"},
    )
    async_db.add(item)
    await async_db.flush()
    revision = FileRevision(
        workspace_id=workspace.id,
        item_id=item.id,
        created_by=user.id,
        page_count=1,
        page_geometry=[[0, 0, 100, 100]],
        processing_state="ready",
        file=FileObject(
            backend="documents",
            filename=str(uuid4()),
            content_type="application/pdf",
            size=10,
            metadata={"original_name": "annotated.pdf"},
        ),
    )
    async_db.add(revision)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Annotation restore", expires_in_days=30)
    context = {"workspace_id": workspace.id, "item_id": item.id}

    async with mcp_client(async_session_factory) as (client, _app):
        annotation = await _tool(
            client,
            grant.raw_token,
            "annotations.create_annotation",
            **context,
            id=str(uuid4()),
            revision_id=revision.id,
            page_index=0,
            kind="note",
            body="Keep this note",
            payload={"type": "note", "rect": {"x": 1, "y": 2, "width": 20, "height": 10}},
        )
        annotation_context = context | {"annotation_id": annotation["id"]}
        reply = await _tool(
            client,
            grant.raw_token,
            "annotations.create_reply",
            **annotation_context,
            id=str(uuid4()),
            body="Keep this reply",
        )
        reply_context = annotation_context | {"reply_id": reply["id"]}
        await _tool(
            client,
            grant.raw_token,
            "annotations.delete_reply",
            **reply_context,
            version=reply["version"],
        )
        restored_reply = await _tool(
            client,
            grant.raw_token,
            "annotations.restore_reply",
            **reply_context,
            version=reply["version"] + 1,
        )
        assert restored_reply["body"] == "Keep this reply"
        await _tool(
            client,
            grant.raw_token,
            "annotations.delete_annotation",
            **annotation_context,
            version=annotation["version"],
        )
        assert (await _tool(client, grant.raw_token, "annotations.list_annotations", **context))[
            "total"
        ] == 0
        restored = await _tool(
            client,
            grant.raw_token,
            "annotations.restore_annotation",
            **annotation_context,
            version=annotation["version"] + 1,
        )
        assert restored["body"] == "Keep this note"
        assert [row["body"] for row in restored["replies"]] == ["Keep this reply"]
        listed = await _tool(client, grant.raw_token, "annotations.list_annotations", **context)
        assert [row["id"] for row in listed["annotations"]] == [annotation["id"]]


@pytest.mark.parametrize(("restriction", "expected_status"), [("viewer", 403), ("frozen", 409)])
async def test_import_and_item_deletion_keep_workspace_write_restrictions(
    async_db, async_session_factory, monkeypatch, restriction, expected_status
):
    owner = User(username="mcp-restricted-owner", password_hash="unused")
    async_db.add(owner)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, owner)
    actor = owner
    if restriction == "viewer":
        actor = User(username="mcp-restricted-viewer", password_hash="unused")
        async_db.add(actor)
        await async_db.flush()
        async_db.add(
            WorkspaceMember(workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.viewer)
        )
    else:
        workspace.governance_frozen_at = datetime.now(UTC)
    item = Item(
        workspace_id=workspace.id,
        created_by=owner.id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Retained Item"},
    )
    async_db.add(item)
    await async_db.commit()
    grant = await create_api_token(async_db, actor, "Restricted client", expires_in_days=30)
    exchange = MockExchange(lambda _request: pytest.fail("Denied imports must not call Providers"))
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )

    async with mcp_client(async_session_factory) as (client, _app):
        for tool_name, arguments in (
            ("imports.stage_identifiers_import", {"identifiers": ["10.1234/denied"]}),
            ("items.delete_library_item", {"item_id": item.id}),
        ):
            response = await _call(
                client, grant.raw_token, tool_name, {"workspace_id": workspace.id, **arguments}
            )
            result = response.json()["result"]
            assert result["isError"] is True
            assert str(expected_status) in result["content"][0]["text"]
        visible = await _tool(
            client, grant.raw_token, "library.search_items", workspace_id=workspace.id
        )
        assert [row["id"] for row in visible["items"]] == [str(item.id)]
    assert exchange.requests == []


async def test_generated_tools_match_the_fixed_allowlist_and_annotations(async_session_factory):
    async with mcp_client(async_session_factory) as (_client, app):
        server = app.state.mcp_server
        generated = {name: await server.get_tool(name) for name in TOOL_ALLOWLIST}

    assert all(tool is not None for tool in generated.values())
    assert not any(name.startswith("admin.") for name in TOOL_ALLOWLIST)
    assert not any(
        "session" in name or "content" in name or "upload" in name for name in TOOL_ALLOWLIST
    )
    assert not TOOL_ALLOWLIST & {
        "account.account_summary",
        "workspaces.create_user_workspace",
        "workspaces.delete_user_workspace",
        "workspaces.change_workspace_member_role",
        "imports.stage_pdf_import",
        "imports.stage_bibliography_import",
        "imports.retry_import_batch",
        "library_exports.download_workspace_bibliography",
    }
    annotations = {name: tool.annotations for name, tool in generated.items()}
    assert annotations["discovery.search_discovery"].open_world_hint is True
    assert annotations["documents.list_documents"].read_only_hint is True
    assert annotations["annotations.delete_annotation"].destructive_hint is True
    assert annotations["annotations.delete_reply"].destructive_hint is True
    assert annotations["workspaces.get_workspaces"].read_only_hint is True
    assert annotations["imports.stage_identifiers_import"].read_only_hint is False
    assert annotations["imports.stage_identifiers_import"].open_world_hint is True
    assert annotations["imports.stage_identifiers_import"].idempotent_hint is False
    assert annotations["imports.commit_staged_import"].read_only_hint is False
    assert annotations["imports.commit_staged_import"].open_world_hint is False
    assert annotations["imports.delete_import"].destructive_hint is True
    assert annotations["tools.merge_user_tags"].destructive_hint is True
    assert annotations["tools.delete_user_tag"].destructive_hint is True
    assert annotations["items.delete_library_item"].destructive_hint is True
    assert annotations["annotations.restore_annotation"].read_only_hint is False


async def test_tool_search_discovers_curated_tools(async_session_factory):
    async with mcp_client(async_session_factory) as (_client, app):
        result = await app.state.mcp_server.call_tool(
            "search_tools", {"query": "update project"}, run_middleware=False
        )
        schema = await app.state.mcp_server.call_tool(
            "get_schema", {"tools": ["projects.update_project"]}, run_middleware=False
        )

    assert result.is_error is False
    assert "### projects.update_project" in result.content[0].text
    assert schema.is_error is False
    (matching_tool,) = json.loads(schema.content[0].text)
    assert set(matching_tool["inputSchema"]["properties"]) == {
        "workspace_id",
        "project_id",
        "name",
        "description",
        "participation",
    }


async def test_search_summaries_keep_full_constraints_and_annotations_available(
    async_db, async_session_factory
):
    user = User(username="mcp-schema-reader", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, user)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Schema discovery", expires_in_days=30)

    async with mcp_client(async_session_factory) as (client, _app):
        discovered = await _call(
            client, grant.raw_token, "search_tools", {"query": "import DOI identifiers"}
        )
        result = discovered.json()["result"]
        assert result["isError"] is False
        summary = result["content"][0]["text"]
        names = [
            line.removeprefix("### ") for line in summary.splitlines() if line.startswith("### ")
        ]
        assert "imports.stage_identifiers_import" in names
        assert len(names) <= 5
        definitions = await _schemas(client, grant.raw_token, *names)
        assert {definition["name"] for definition in definitions} == set(names)
        assert len(summary) < len(json.dumps(definitions, separators=(",", ":"))) / 10
        stage = next(
            definition
            for definition in definitions
            if definition["name"] == "imports.stage_identifiers_import"
        )
        identifiers = stage["inputSchema"]["properties"]["identifiers"]
        assert identifiers["minItems"] == 1
        assert identifiers["maxItems"] == 50
        assert stage["annotations"]["openWorldHint"] is True
        assert stage["annotations"]["readOnlyHint"] is False
        assert "$defs" in stage["outputSchema"]
        invalid = await _call(
            client,
            grant.raw_token,
            "call_tool",
            {
                "name": stage["name"],
                "arguments": {"workspace_id": workspace.id, "identifiers": []},
            },
        )
        assert invalid.json()["result"]["isError"] is True


async def test_schema_lookup_uses_the_curated_and_authorized_catalog(
    async_db, async_session_factory
):
    user = User(username="mcp-schema-visibility", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    await provision_initial_workspace(async_db, user)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Schema visibility", expires_in_days=30)

    async with mcp_client(async_session_factory) as (client, app):

        @app.state.mcp_server.tool(auth=lambda _ctx: False)
        def hidden_schema_probe(secret: str) -> str:
            return secret

        definitions = await _schemas(
            client,
            grant.raw_token,
            "library.search_items",
            "workspaces.delete_user_workspace",
            "hidden_schema_probe",
        )

    visible = [definition for definition in definitions if "name" in definition]
    assert [definition["name"] for definition in visible] == ["library.search_items"]
    assert definitions[-1]["not_found"] == [
        "workspaces.delete_user_workspace",
        "hidden_schema_probe",
    ]


async def test_generated_tool_schemas_come_from_the_api_contract(async_session_factory):
    async with mcp_client(async_session_factory) as (_client, app):
        server = app.state.mcp_server
        tools = {name: await server.get_tool(name) for name in TOOL_ALLOWLIST}

    assert set(tools["library.search_items"].parameters["properties"]) == {
        "workspace_id",
        "query",
        "tag",
        "project",
        "import_batch",
        "year",
        "keyword",
        "author",
        "limit",
        "offset",
        "sort",
        "direction",
        "has_files",
        "has_tags",
        "has_projects",
        "reference_type",
        "keyword_exact",
        "author_last_name",
        "author_first_name",
        "publication_title",
    }
    assert set(tools["library.get_item_facets"].parameters["properties"]) == set(
        tools["library.search_items"].parameters["properties"]
    )
    assert set(tools["projects.update_project"].parameters["properties"]) == {
        "workspace_id",
        "project_id",
        "name",
        "description",
        "participation",
    }
    assert set(tools["projects.add_project_participant"].parameters["properties"]) == {
        "workspace_id",
        "project_id",
        "username",
    }
    assert set(tools["projects.remove_project_participant"].parameters["properties"]) == {
        "workspace_id",
        "project_id",
        "user_id",
    }
    assert set(tools["annotations.update_annotation"].parameters["properties"]) == {
        "workspace_id",
        "item_id",
        "annotation_id",
        "version",
        "page_index",
        "kind",
        "payload",
        "body",
        "selected_text",
    }


async def test_generated_library_tool_calls_api_and_preserves_mcp_audit_provenance(
    async_db, async_session_factory
):
    user = User(username="generated-mcp-writer", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    await provision_initial_workspace(async_db, user)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Generated MCP", expires_in_days=30)

    async with mcp_client(async_session_factory) as (client, _app):
        response = await _call(
            client,
            grant.raw_token,
            "library.create_library_item",
            {
                "workspace_id": fixture_workspace_id(user),
                "metadata": {
                    "id": "https://doi.org/10.1000/generated",
                    "type": "Document",
                    "title": "Created through generated MCP",
                },
            },
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
            AuditEvent.action == "item.create", AuditEvent.target_id == str(item_id)
        )
    )
    assert event is not None
    assert event.detail == json_payload({
        "invocation": {
            "protocol": "mcp",
            "operation": "library.create_library_item",
            "api_token_id": grant.token_id,
            "client_id": f"quirebase-api-token:{grant.token_id}",
        }
    })


async def test_tool_search_proxy_calls_the_curated_tool(async_db, async_session_factory):
    user = User(username="tool-search-writer", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    await provision_initial_workspace(async_db, user)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Tool search", expires_in_days=30)

    async with mcp_client(async_session_factory) as (client, _app):
        discovered = await _call(
            client,
            grant.raw_token,
            "search_tools",
            {"query": "create bibliographic item"},
        )
        (definition,) = await _schemas(client, grant.raw_token, "library.create_library_item")
        metadata = definition["inputSchema"]["$defs"]["Work"]
        assert "title" in metadata["properties"]
        assert metadata["additionalProperties"] is False
        created = await _call(
            client,
            grant.raw_token,
            "call_tool",
            {
                "name": definition["name"],
                "arguments": {
                    "workspace_id": fixture_workspace_id(user),
                    "metadata": {
                        "id": "urn:uuid:00000000-0000-4000-8000-000000000001",
                        "type": "Document",
                        "title": "Created through tool search",
                    },
                },
            },
        )

    assert discovered.status_code == 200
    summary = discovered.json()["result"]["content"][0]["text"]
    assert "### library.create_library_item" in summary
    assert created.status_code == 200
    created_result = created.json()["result"]
    assert created_result["isError"] is False
    item_id = created_result["structuredContent"]["id"]
    event = await async_db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "item.create", AuditEvent.target_id == str(item_id)
        )
    )
    assert event is not None
    assert event.detail["invocation"]["operation"] == "library.create_library_item"


async def test_generated_tool_returns_api_version_conflict_as_mcp_error(
    async_db, async_session_factory
):
    user = User(username="generated-mcp-conflict", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    await provision_initial_workspace(async_db, user)
    await async_db.commit()
    grant = await create_api_token(async_db, user, "Generated MCP conflict", expires_in_days=30)

    async with mcp_client(async_session_factory) as (client, _app):
        created = await _call(
            client,
            grant.raw_token,
            "library.create_library_item",
            {
                "workspace_id": fixture_workspace_id(user),
                "metadata": {
                    "id": "urn:uuid:00000000-0000-4000-8000-000000000001",
                    "type": "Document",
                    "title": "Versioned Item",
                },
            },
        )
        item_id = created.json()["result"]["structuredContent"]["id"]
        arguments = {
            "workspace_id": fixture_workspace_id(user),
            "item_id": item_id,
            "expected_version": 1,
            "metadata": {
                "id": "urn:uuid:00000000-0000-4000-8000-000000000001",
                "type": "Document",
                "title": "First update",
            },
        }
        first = await _call(client, grant.raw_token, "library.update_library_item", arguments, 2)
        conflict = await _call(client, grant.raw_token, "library.update_library_item", arguments, 3)

    assert first.json()["result"]["isError"] is False
    conflict_result = conflict.json()["result"]
    assert conflict_result["isError"] is True
    assert "409" in conflict_result["content"][0]["text"]
    assert "version" in conflict_result["content"][0]["text"].casefold()


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("library.search_items", {}),
        ("get_schema", {"tools": ["library.search_items"]}),
    ],
)
async def test_generated_tool_does_not_fall_back_to_cookie_auth(
    async_db, async_session_factory, tool_name, arguments
):
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
            json=json_payload({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }),
        )
        invalid = await _call(client, "invalid", tool_name, arguments)

    assert missing.status_code == 401
    assert invalid.status_code == 401
