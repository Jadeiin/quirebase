from __future__ import annotations

import json
from uuid import uuid4

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import func, select

from quirebase.mcp import (
    TOOL_ALLOWLIST,
    RequestIdentity,
    ToolPolicy,
    create_mcp_server,
)
from quirebase.models import (
    AuditEvent,
    FileRevision,
    Item,
    PdfAnnotation,
    PdfAnnotationReply,
    Project,
    ProjectItem,
    ProjectMember,
    Tag,
    User,
)


def _server(session_factory, identity: RequestIdentity):
    return create_mcp_server(identity_provider=lambda: identity, session_factory=session_factory)


async def _call(server, name: str, arguments: dict):
    return await server.call_tool(name, arguments)


def test_tool_policy_filters_discovery_and_enforces_calls():
    policy = ToolPolicy()

    assert policy.visible_tools() == TOOL_ALLOWLIST
    policy.require("library.search")
    with pytest.raises(ToolError, match="unknown tool"):
        policy.require("admin.delete_user")


@pytest.mark.anyio
async def test_registered_tools_match_the_server_allowlist():
    server = create_mcp_server(identity_provider=lambda: RequestIdentity("unused"))

    registered = await server.list_tools()

    assert {tool.name for tool in registered} == TOOL_ALLOWLIST
    assert not any(name.startswith("admin.") for name in TOOL_ALLOWLIST)
    assert not any("fulltext" in name or "full_text" in name for name in TOOL_ALLOWLIST)
    annotations = {tool.name: tool.annotations for tool in registered}
    assert annotations["discovery.search"].open_world_hint is True
    assert annotations["documents.list"].read_only_hint is True
    assert annotations["annotations.delete"].destructive_hint is True
    assert annotations["annotation_replies.delete"].destructive_hint is True


@pytest.mark.anyio
async def test_library_search_returns_only_items_visible_to_token_user(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="mcp-reader", password_hash="unused")
    other = User(username="other-owner", password_hash="unused")
    db.add_all([user, other])
    await db.flush()
    own = Item(title="<i>Visible</i> Item", created_by=user.id, doi="10.1/visible")
    hidden = Item(title="Hidden Item", created_by=other.id)
    db.add_all([own, hidden])
    await db.commit()

    server = _server(async_session_factory, RequestIdentity(user.id))
    result = await _call(server, "library.search", {"query": ""})

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["total"] == 1
    assert result.structured_content["items"] == [
        {
            "id": own.id,
            "title_html": "<i>Visible</i> Item",
            "authors": None,
            "publication_date": None,
            "publication_title": None,
            "doi": "10.1/visible",
            "version": 1,
        }
    ]


@pytest.mark.anyio
async def test_library_get_item_reuses_project_access(async_db, async_session_factory):
    db = async_db
    reader = User(username="project-reader", password_hash="unused")
    owner = User(username="project-owner", password_hash="unused")
    db.add_all([reader, owner])
    await db.flush()
    item = Item(title="Shared Item", abstract="Shared abstract", created_by=owner.id)
    project = Project(name="Shared project", created_by=owner.id)
    db.add_all([item, project])
    await db.flush()
    db.add_all([
        ProjectMember(project_id=project.id, user_id=reader.id, role="viewer"),
        ProjectItem(project_id=project.id, item_id=item.id),
    ])
    await db.commit()

    server = _server(async_session_factory, RequestIdentity(reader.id))
    result = await _call(server, "library.get_item", {"item_id": item.id})

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["id"] == item.id
    assert result.structured_content["abstract_html"] == "Shared abstract"


@pytest.mark.anyio
async def test_library_get_item_conceals_inaccessible_item(async_db, async_session_factory):
    db = async_db
    reader = User(username="mcp-outsider", password_hash="unused")
    owner = User(username="private-owner", password_hash="unused")
    db.add_all([reader, owner])
    await db.flush()
    item = Item(title="Private Item", created_by=owner.id)
    db.add(item)
    await db.commit()
    server = _server(async_session_factory, RequestIdentity(reader.id))

    with pytest.raises(ToolError, match="item not found"):
        await _call(server, "library.get_item", {"item_id": item.id})


@pytest.mark.anyio
async def test_library_create_item_uses_token_user_as_owner(async_db, async_session_factory):
    db = async_db
    user = User(username="mcp-writer", password_hash="unused")
    db.add(user)
    await db.commit()

    identity = RequestIdentity(
        user.id,
        client_id="quirebase-api-token:write-token",
        api_token_id="write-token",
    )
    result = await _call(
        _server(async_session_factory, identity),
        "library.create_item",
        {"metadata": {"title": "Created through MCP", "doi": "10.1/mcp"}},
    )

    assert result.is_error is False
    assert result.structured_content is not None
    item = await db.get(Item, result.structured_content["id"])
    assert item is not None
    assert item.created_by == user.id
    assert item.title == "Created through MCP"
    business_event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "item.create", AuditEvent.target_id == item.id
        )
    )
    assert business_event is not None
    assert json.loads(business_event.detail) == {
        "invocation": {
            "protocol": "mcp",
            "operation": "library.create_item",
            "api_token_id": "write-token",
            "client_id": "quirebase-api-token:write-token",
        }
    }


@pytest.mark.anyio
async def test_project_and_tag_mutations_reuse_item_permissions(async_db, async_session_factory):
    db = async_db
    owner = User(username="mcp-project-owner", password_hash="unused")
    outsider = User(username="mcp-project-outsider", password_hash="unused")
    db.add_all([owner, outsider])
    await db.flush()
    item = Item(title="Owned", created_by=owner.id)
    hidden = Item(title="Hidden", created_by=outsider.id)
    project = Project(name="MCP project", created_by=owner.id)
    db.add_all([item, hidden, project])
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=owner.id, role="owner"))
    await db.commit()
    server = _server(async_session_factory, RequestIdentity(owner.id))

    added = await _call(server, "projects.add_item", {"project_id": project.id, "item_id": item.id})
    tagged = await _call(server, "tags.add_to_item", {"item_id": item.id, "name": "MCP"})

    assert added.is_error is False
    assert tagged.is_error is False
    assert await db.get(ProjectItem, (project.id, item.id)) is not None
    tag = await db.get(Tag, tagged.structured_content["id"])
    assert tag is not None and tag.name == "MCP"
    with pytest.raises(ToolError, match="project or item not found"):
        await _call(server, "projects.add_item", {"project_id": project.id, "item_id": hidden.id})


@pytest.mark.anyio
async def test_documents_list_returns_metadata_but_not_content_or_storage_keys(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="mcp-doc-reader", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(title="Documented", created_by=user.id)
    db.add(item)
    await db.flush()
    revision = FileRevision(
        item_id=item.id,
        object_key="secret/storage-key.pdf",
        size=123,
        mime_type="application/pdf",
        original_name="paper.pdf",
        page_count=2,
        page_geometry="[]",
        full_text="plain text intentionally excluded",
        processing_state="ready",
        created_by=user.id,
    )
    db.add(revision)
    await db.commit()

    result = await _call(
        _server(async_session_factory, RequestIdentity(user.id)),
        "documents.list",
        {"item_id": item.id},
    )

    assert result.is_error is False
    assert result.structured_content is not None
    serialized = str(result.structured_content)
    assert "paper.pdf" in serialized
    assert "plain text intentionally excluded" not in serialized
    assert "secret/storage-key.pdf" not in serialized


@pytest.mark.anyio
async def test_item_metadata_can_round_trip_without_losing_replaceable_fields(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="mcp-round-trip", password_hash="unused")
    db.add(user)
    await db.commit()
    server = _server(async_session_factory, RequestIdentity(user.id))
    metadata = {
        "title": "Complete metadata",
        "abstract": "Abstract",
        "keywords": ["one", "two"],
        "publication_date": "2026-08-30",
        "publication_title": "Journal",
        "reference_type": "article",
        "volume": "12",
        "issue": "3",
        "pages": "10-20",
        "affiliation": "Institute",
        "publisher": "Publisher",
        "place_published": "Shanghai",
        "journal_abbreviation": "J Test",
        "bibtex_key": "Author2026Complete",
        "bibtex_type": "article",
        "urls": ["https://example.test/paper"],
        "authors": [{"last_name": "Author", "first_name": "Alice", "is_corresponding": True}],
        "editors": [{"last_name": "Editor", "first_name": "Eve"}],
        "doi": "10.1000/complete",
        "identifiers": [{"provider": "pmid", "value": "123456"}],
        "custom_fields": [
            {"name": "rating", "value": 5},
            {"name": "flags", "value": ["reviewed", "important"]},
        ],
    }
    created = await _call(server, "library.create_item", {"metadata": metadata})
    assert created.structured_content is not None
    item_id = created.structured_content["id"]

    read = await _call(server, "library.get_item", {"item_id": item_id})
    assert read.structured_content is not None
    returned_metadata = read.structured_content["metadata"]

    updated = await _call(
        server,
        "library.update_item",
        {
            "item_id": item_id,
            "expected_version": read.structured_content["version"],
            "metadata": returned_metadata,
        },
    )
    reread = await _call(server, "library.get_item", {"item_id": item_id})

    assert updated.is_error is False
    assert reread.structured_content is not None
    assert reread.structured_content["metadata"] == returned_metadata


@pytest.mark.anyio
async def test_mcp_reads_and_failures_do_not_create_audit_events(async_db, async_session_factory):
    db = async_db
    user = User(username="mcp-audited", password_hash="unused")
    db.add(user)
    await db.commit()
    identity = RequestIdentity(
        user_id=user.id,
        client_id="quirebase-api-token:token-123",
        api_token_id="token-123",
    )
    server = _server(async_session_factory, identity)

    result = await _call(server, "library.search", {"query": ""})
    with pytest.raises(ToolError, match="item not found"):
        await _call(server, "library.get_item", {"item_id": "missing"})

    assert result.is_error is False
    assert (
        await db.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.actor_id == user.id)
        )
        == 0
    )


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "annotations.create",
            {
                "item_id": "item-id",
                "revision_id": "revision-id",
                "kind": "note",
                "segments": [{"page_index": 0, "anchor_x": 10, "anchor_y": 20}],
                "scope": "project",
            },
        ),
        (
            "annotations.update",
            {
                "item_id": "item-id",
                "annotation_id": "annotation-id",
                "version": 0,
            },
        ),
    ],
)
@pytest.mark.anyio
async def test_annotation_handler_validation_does_not_create_an_audit_event(
    async_db, async_session_factory, tool_name, arguments
):
    db = async_db
    user = User(username=f"mcp-invalid-{tool_name}", password_hash="unused")
    db.add(user)
    await db.commit()
    server = _server(async_session_factory, RequestIdentity(user.id, client_id="test-client"))

    with pytest.raises(ToolError):
        await _call(server, tool_name, arguments)

    assert (
        await db.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.actor_id == user.id)
        )
        == 0
    )


@pytest.mark.anyio
async def test_mcp_annotation_tools_use_the_canonical_snapshot_contract(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="mcp-canonical-annotations", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(title="Canonical annotations", created_by=user.id)
    db.add(item)
    await db.flush()
    revision = FileRevision(
        item_id=item.id,
        object_key="objects/canonical.pdf",
        size=10,
        mime_type="application/pdf",
        original_name="canonical.pdf",
        page_count=1,
        page_geometry="[[0,0,200,300]]",
        processing_state="ready",
        created_by=user.id,
    )
    db.add(revision)
    await db.commit()
    server = _server(async_session_factory, RequestIdentity(user.id, client_id="test-client"))
    annotation_id = str(uuid4())
    payload = {
        "type": "note",
        "rect": {"x": 10, "y": 20, "width": 24, "height": 24},
        "style": {"stroke_color": "#3366CC", "opacity": 0.8},
    }

    created = await _call(
        server,
        "annotations.create",
        {
            "item_id": item.id,
            "id": annotation_id,
            "revision_id": revision.id,
            "page_index": 0,
            "kind": "note",
            "payload": payload,
            "body": "First comment",
        },
    )
    assert created.structured_content is not None
    assert created.structured_content["id"] == annotation_id
    assert created.structured_content["payload"]["type"] == "note"
    assert created.structured_content["editable"] is True

    listed = await _call(
        server,
        "annotations.list",
        {"item_id": item.id, "revision_id": revision.id},
    )
    assert listed.structured_content is not None
    assert listed.structured_content["result"][0]["id"] == annotation_id

    reply_id = str(uuid4())
    reply = await _call(
        server,
        "annotation_replies.create",
        {
            "item_id": item.id,
            "annotation_id": annotation_id,
            "id": reply_id,
            "body": "MCP reply",
        },
    )
    assert reply.structured_content is not None
    assert reply.structured_content["body"] == "MCP reply"
    updated_reply = await _call(
        server,
        "annotation_replies.update",
        {
            "item_id": item.id,
            "annotation_id": annotation_id,
            "reply_id": reply_id,
            "version": 1,
            "body": "Updated MCP reply",
        },
    )
    assert updated_reply.structured_content is not None
    assert updated_reply.structured_content["version"] == 2
    await _call(
        server,
        "annotation_replies.delete",
        {
            "item_id": item.id,
            "annotation_id": annotation_id,
            "reply_id": reply_id,
            "version": 2,
        },
    )
    reply_record = await db.get(PdfAnnotationReply, reply_id)
    assert reply_record is not None and reply_record.deleted_at is not None

    updated = await _call(
        server,
        "annotations.update",
        {
            "item_id": item.id,
            "annotation_id": annotation_id,
            "version": 1,
            "page_index": 0,
            "kind": "note",
            "scope": "private",
            "payload": payload,
            "body": "Updated comment",
        },
    )
    assert updated.structured_content is not None
    assert updated.structured_content["version"] == 2
    assert updated.structured_content["body"] == "Updated comment"

    deleted = await _call(
        server,
        "annotations.delete",
        {"item_id": item.id, "annotation_id": annotation_id, "version": 2},
    )
    assert deleted.structured_content == {"ok": True}
    record = await db.get(PdfAnnotation, annotation_id)
    assert record is not None and record.deleted_at is not None and record.version == 3
    actions = set(
        await db.scalars(select(AuditEvent.action).where(AuditEvent.target_id == annotation_id))
    )
    assert actions == {"annotation.create", "annotation.update", "annotation.delete"}
