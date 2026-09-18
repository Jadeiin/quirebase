from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_http import authenticated_async_client

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.library import (
    AnnotationsWorkspace,
    DiscussionWorkspace,
    FilesWorkspace,
    MetadataWorkspace,
    OrganizeWorkspace,
    SummaryWorkspace,
    WorkspaceSection,
    open_item_workspace,
)
from quirebase.models import (
    Attachment,
    AttachmentRole,
    AuditEvent,
    DiscussionMessage,
    Item,
    ItemIdentifier,
    ItemRead,
    ItemTag,
    LoginSession,
    PdfAnnotation,
    Project,
    ProjectItem,
    ProjectMember,
    Tag,
    User,
)
from quirebase.web.api import documents as documents_api


@pytest.mark.anyio
async def test_open_summary_workspace_returns_a_typed_view_and_records_reading(async_db):
    db = async_db
    user = User(username="workspace-reader", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(title="Typed workspace", created_by=user.id)
    db.add(item)
    await db.commit()

    view = await open_item_workspace(db, user, item.id, WorkspaceSection.summary)

    assert isinstance(view, SummaryWorkspace)
    assert view.item.id == item.id
    assert view.item_owner.id == user.id
    assert view.revision_count == 0
    assert view.attachment_count == 0
    assert await db.get(ItemRead, (user.id, item.id)) is not None


def test_workspace_section_rejects_unknown_names_before_query_branching():
    with pytest.raises(ResourceNotFound, match="unknown item section"):
        WorkspaceSection.parse("unknown")


@pytest.mark.anyio
async def test_open_item_workspace_returns_a_section_specific_view(async_db):
    db = async_db
    user = User(username="section-reader", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(title="Section views", created_by=user.id)
    db.add(item)
    await db.commit()

    expected_types = {
        WorkspaceSection.summary: SummaryWorkspace,
        WorkspaceSection.metadata: MetadataWorkspace,
        WorkspaceSection.files: FilesWorkspace,
        WorkspaceSection.organize: OrganizeWorkspace,
        WorkspaceSection.annotations: AnnotationsWorkspace,
        WorkspaceSection.discussion: DiscussionWorkspace,
    }
    for section, expected_type in expected_types.items():
        assert isinstance(await open_item_workspace(db, user, item.id, section), expected_type)


@pytest.mark.anyio
async def test_inaccessible_item_never_records_reading(async_db):
    db = async_db
    owner = User(username="workspace-owner", password_hash="unused")
    outsider = User(username="workspace-outsider", password_hash="unused")
    db.add_all([owner, outsider])
    await db.flush()
    item = Item(title="Private workspace", created_by=owner.id)
    db.add(item)
    await db.commit()
    outsider_id, item_id = outsider.id, item.id

    with pytest.raises(ResourceUnavailable, match="item not found"):
        await open_item_workspace(db, outsider, item_id, WorkspaceSection.summary)

    assert await db.get(ItemRead, (outsider_id, item_id)) is None


@pytest.mark.anyio
async def test_item_workspace_separates_page_responsibilities(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        item.urls = (
            "https://publisher.example/article\n"
            "https://publisher.example/files/reading-copy.PDF?download=1"
        )
        tag = Tag(name="User priority", created_by=item.created_by)
        db.add(tag)
        await db.flush()
        db.add_all([
            ItemTag(item_id=item.id, tag_id=tag.id),
            ItemIdentifier(item_id=item.id, provider="openalex", value="W123"),
            ItemIdentifier(item_id=item.id, provider="arxiv", value="2401.00001"),
        ])
        await db.commit()
        summary = await client.get(f"/api/v1/items/{item.id}/workspace")
        assert summary.status_code == 200
        assert summary.json()["latest_revision"]["id"] == revision.id
        assert summary.json()["thumbnail"] is None
        assert summary.json()["tags"] == [{"id": tag.id, "name": "User priority"}]
        assert {tuple(row.values()) for row in summary.json()["identifiers"]} == {
            ("openalex", "W123"),
            ("arxiv", "2401.00001"),
        }

        metadata = await client.get(f"/api/v1/items/{item.id}")
        assert metadata.status_code == 200
        assert "reading-copy.PDF" in metadata.text

        files = await client.get(f"/api/v1/items/{item.id}/documents")
        assert files.status_code == 200
        assert revision.original_name in files.text

        organize = await client.get("/api/v1/tags")
        assert organize.status_code == 200
        assert organize.json()[0]["name"] == "User priority"

        created = await client.post(
            f"/api/v1/items/{item.id}/annotations",
            headers={"X-CSRF-Token": "test-csrf"},
            json={
                "id": str(uuid4()),
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "highlight",
                "scope": "private",
                "selected_text": "A useful result",
                "payload": {
                    "type": "highlight",
                    "rect": {"x": 10, "y": 10, "width": 20, "height": 10},
                    "segment_rects": [{"x": 10, "y": 10, "width": 20, "height": 10}],
                },
            },
        )
        assert created.status_code == 201
        annotations = await client.get(
            f"/api/v1/items/{item.id}/annotations", params={"revision_id": revision.id}
        )
        assert annotations.status_code == 200
        assert annotations.json()[0]["selected_text"] == "A useful result"
        assert annotations.json()[0]["page_index"] == 0

        discussion = await client.get(f"/api/v1/items/{item.id}/discussions")
        assert discussion.status_code == 200
        assert discussion.json() == []

        assert (await client.get(f"/api/v1/items/{item.id}/unknown")).status_code == 404
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_remote_documents_are_acquired_server_side_before_upload(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    item_id = item.id

    async def content():  # ruff: ignore[unused-async] - async upload source contract
        yield b"remote content"

    @asynccontextmanager
    async def acquire_remote_pdf(source, _settings, _max_bytes):
        assert source == "https://publisher.example/article.pdf"
        yield SimpleNamespace(
            content=content(), filename="article.pdf", media_type="application/pdf"
        )

    @asynccontextmanager
    async def acquire_remote_attachment(source, _max_bytes):
        assert source == "https://publisher.example/supplement.zip"
        yield SimpleNamespace(
            content=content(), filename="supplement.zip", media_type="application/zip"
        )

    store_revision = AsyncMock(return_value=SimpleNamespace(workflow_id="revision-workflow"))
    store_attachment = AsyncMock(return_value=SimpleNamespace(workflow_id="attachment-workflow"))
    monkeypatch.setattr(documents_api, "acquire_remote_pdf", acquire_remote_pdf)
    monkeypatch.setattr(documents_api, "acquire_remote_attachment", acquire_remote_attachment)
    monkeypatch.setattr(documents_api, "store_pdf_revision", store_revision)
    monkeypatch.setattr(documents_api, "create_attachment", store_attachment)

    try:
        revision = await client.post(
            f"/api/v1/items/{item_id}/revisions/remote",
            json={"source": "https://publisher.example/article.pdf"},
        )
        assert revision.status_code == 202
        assert revision.json() == {"id": "revision-workflow", "version": None}
        assert store_revision.await_args.args[4] == "article.pdf"

        attachment = await client.post(
            f"/api/v1/items/{item_id}/attachments/remote",
            json={
                "source": "https://publisher.example/supplement.zip",
                "graphical_abstract": False,
            },
        )
        assert attachment.status_code == 202
        assert attachment.json() == {"id": "attachment-workflow", "version": None}
        assert store_attachment.await_args.args[4] == "supplement.zip"
        assert store_attachment.await_args.args[5] == "application/zip"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_project_editor_can_edit_item_without_seeing_permanent_delete(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    owner_client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    editor = User(username="workspace-editor", password_hash="unused")
    project = Project(name="Shared editing", created_by=item.created_by)
    db.add_all([editor, project])
    await db.flush()
    db.add_all([
        ProjectItem(project_id=project.id, item_id=item.id),
        ProjectMember(project_id=project.id, user_id=editor.id, role="editor"),
        LoginSession(
            token_hash=token_hash("editor-session"),
            user_id=editor.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    ])
    await db.commit()

    try:
        owner_page = await owner_client.get(f"/api/v1/items/{item.id}/workspace")
        assert owner_page.json()["permissions"] == {"edit": True, "delete": True}

        editor_client = owner_client
        editor_client.cookies.set(get_settings().session_cookie, "editor-session")
        editor_page = await editor_client.get(f"/api/v1/items/{item.id}/workspace")
        assert editor_page.status_code == 200
        assert editor_page.json()["permissions"] == {"edit": True, "delete": False}

        view = await open_item_workspace(db, editor, item.id, WorkspaceSection.summary)
        assert view.can_edit is True
        assert view.can_delete is False
    finally:
        await owner_client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_citation_export_and_project_removal(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        project = Project(name="Focused review", created_by=item.created_by)
        db.add(project)
        await db.flush()
        db.add_all([
            ProjectMember(project_id=project.id, user_id=item.created_by, role="owner"),
            ProjectItem(project_id=project.id, item_id=item.id),
        ])
        await db.commit()

        exported = await client.get(f"/api/v1/items/{item.id}/bibliography?file_format=bibtex")
        assert exported.status_code == 200
        assert item.title in exported.text
        assert "quirebase-export.bib" in exported.headers["content-disposition"]

        cited = await client.get(f"/api/v1/items/{item.id}/bibliography?file_format=csl&style=apa")
        assert cited.status_code == 200
        assert item.title in cited.text
        assert "quirebase-citations.txt" in cited.headers["content-disposition"]

        plain_download = await client.get(f"/api/v1/items/{item.id}/archive")
        assert "Paper-pdfs.zip" in plain_download.headers["content-disposition"]
        annotated_download = await client.get(
            f"/api/v1/items/{item.id}/archive?include_annotations=true"
        )
        assert "Paper-annotated-pdfs.zip" in annotated_download.headers["content-disposition"]

        item.title = "中文论文"
        item.bibtex_id = None
        await db.commit()
        unicode_download = await client.get(f"/api/v1/items/{item.id}/archive")
        assert unicode_download.status_code == 200
        assert "filename*=utf-8''" in unicode_download.headers["content-disposition"]

        removed = await client.delete(f"/api/v1/projects/{project.id}/items/{item.id}")
        assert removed.status_code == 200
        assert await db.get(ProjectItem, (project.id, item.id)) is None
        assert await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "project.item.remove", AuditEvent.target_id == item.id
            )
        )
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_summary_reports_exact_activity_counts(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        user = await db.get(User, item.created_by)
        assert user is not None
        db.add_all([
            Attachment(
                item_id=item.id,
                object_key="attachments/supplement.txt",
                size=12,
                mime_type="text/plain",
                original_name="supplement.txt",
                created_by=user.id,
            ),
            DiscussionMessage(item_id=item.id, author_id=user.id, body="First"),
            DiscussionMessage(item_id=item.id, author_id=user.id, body="Second"),
            PdfAnnotation(
                file_revision_id=revision.id,
                page_index=0,
                author_id=user.id,
                kind="highlight",
                scope="private",
                payload={
                    "type": "highlight",
                    "rect": {"x": 1, "y": 1, "width": 10, "height": 10},
                    "style": {},
                    "segment_rects": [{"x": 1, "y": 1, "width": 10, "height": 10}],
                },
            ),
            PdfAnnotation(
                file_revision_id=revision.id,
                page_index=0,
                author_id=user.id,
                kind="note",
                scope="private",
                payload={
                    "type": "note",
                    "rect": {"x": 20, "y": 20, "width": 24, "height": 24},
                    "style": {},
                },
            ),
        ])
        await db.commit()

        data = await open_item_workspace(db, user, item.id, WorkspaceSection.summary)

        assert data.revision_count == 1
        assert data.attachment_count == 1
        assert data.annotation_count == 2
        assert data.message_count == 2
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_header_keeps_pdf_link_on_lightweight_sections(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.get(f"/api/v1/items/{item.id}/revisions/{revision.id}/viewer")
        assert response.status_code == 200
        assert response.json()["revision"]["content_url"].endswith(f"/{revision.id}/content")
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_workspace_projection_includes_thumbnail_metadata(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.get(f"/api/v1/items/{item.id}/workspace")
        assert response.status_code == 200
        assert response.json()["thumbnail"] is None

        store = get_object_store()
        thumb = await store.put_object(
            uuid4(), ObjectSuffix.PNG, b"\x89PNG\r\n\x1a\nthumb", max_bytes=100
        )
        revision.thumbnail_object_key = thumb.key
        await db.commit()

        response = await client.get(f"/api/v1/items/{item.id}/workspace")
        assert response.status_code == 200
        assert response.json()["thumbnail"] == {
            "source_kind": "pdf_thumbnail",
            "source_id": revision.id,
        }

        ga_obj = await store.put_object(
            uuid4(), ObjectSuffix.PNG, b"\x89PNG\r\n\x1a\ngraphical", max_bytes=100
        )
        graphical_abstract = Attachment(
            item_id=item.id,
            object_key=ga_obj.key,
            mime_type="image/png",
            role=AttachmentRole.graphical_abstract,
            size=ga_obj.size,
            original_name="graphical_abstract.png",
            created_by=revision.created_by,
        )
        db.add(graphical_abstract)
        await db.commit()

        response = await client.get(f"/api/v1/items/{item.id}/workspace")
        assert response.status_code == 200
        assert response.json()["thumbnail"] == {
            "source_kind": "graphical_abstract",
            "source_id": graphical_abstract.id,
        }
    finally:
        await client.aclose()
        get_settings.cache_clear()
