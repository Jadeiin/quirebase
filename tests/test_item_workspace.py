from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_http import authenticated_client

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
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
from quirebase.web.app import app


def test_open_summary_workspace_returns_a_typed_view_and_records_reading(db):
    user = User(username="workspace-reader", password_hash="unused")
    db.add(user)
    db.flush()
    item = Item(title="Typed workspace", created_by=user.id)
    db.add(item)
    db.commit()

    view = open_item_workspace(db, user, item.id, WorkspaceSection.summary)

    assert isinstance(view, SummaryWorkspace)
    assert view.item.id == item.id
    assert view.item_owner.id == user.id
    assert view.revision_count == 0
    assert view.attachment_count == 0
    assert db.get(ItemRead, (user.id, item.id)) is not None


def test_workspace_section_rejects_unknown_names_before_query_branching():
    with pytest.raises(ResourceNotFound, match="unknown item section"):
        WorkspaceSection.parse("unknown")


def test_open_item_workspace_returns_a_section_specific_view(db):
    user = User(username="section-reader", password_hash="unused")
    db.add(user)
    db.flush()
    item = Item(title="Section views", created_by=user.id)
    db.add(item)
    db.commit()

    expected_types = {
        WorkspaceSection.summary: SummaryWorkspace,
        WorkspaceSection.metadata: MetadataWorkspace,
        WorkspaceSection.files: FilesWorkspace,
        WorkspaceSection.organize: OrganizeWorkspace,
        WorkspaceSection.annotations: AnnotationsWorkspace,
        WorkspaceSection.discussion: DiscussionWorkspace,
    }
    for section, expected_type in expected_types.items():
        assert isinstance(open_item_workspace(db, user, item.id, section), expected_type)


def test_inaccessible_item_never_records_reading(db):
    owner = User(username="workspace-owner", password_hash="unused")
    outsider = User(username="workspace-outsider", password_hash="unused")
    db.add_all([owner, outsider])
    db.flush()
    item = Item(title="Private workspace", created_by=owner.id)
    db.add(item)
    db.commit()

    with pytest.raises(ResourceUnavailable, match="item not found"):
        open_item_workspace(db, outsider, item.id, WorkspaceSection.summary)

    assert db.get(ItemRead, (outsider.id, item.id)) is None


def test_item_workspace_separates_page_responsibilities(db, tmp_path, monkeypatch):
    client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        tag = Tag(name="User priority", created_by=item.created_by)
        db.add(tag)
        db.flush()
        db.add_all([
            ItemTag(item_id=item.id, tag_id=tag.id),
            ItemIdentifier(item_id=item.id, provider="openalex", value="W123"),
            ItemIdentifier(item_id=item.id, provider="arxiv", value="2401.00001"),
        ])
        db.commit()
        summary = client.get(f"/items/{item.id}")
        assert summary.status_code == 200
        assert 'aria-current="page"><span>⌂</span>' in summary.text
        assert "摘要与关键信息" in summary.text
        assert 'x-data="itemDownload"' in summary.text
        assert "x-show=\"format === 'bibtex'\"" in summary.text
        assert "x-show=\"format === 'bibtex' || format === 'csl'\"" in summary.text
        assert 'class="panel publication-snapshot"' in summary.text
        assert 'class="panel reading-files-panel"' in summary.text
        assert 'class="panel discovery-panel"' in summary.text
        assert "User priority" in summary.text
        assert 'href="https://openalex.org/W123"' in summary.text
        assert 'href="https://arxiv.org/abs/2401.00001"' in summary.text
        assert "Workspace activity" not in summary.text
        assert f'action="/items/{item.id}/edit' not in summary.text
        assert f'action="/items/{item.id}/pdf' not in summary.text

        metadata = client.get(f"/items/{item.id}/metadata")
        assert metadata.status_code == 200
        assert "书目元数据" in metadata.text
        assert f'action="/items/{item.id}/edit' in metadata.text

        files = client.get(f"/items/{item.id}/files")
        assert files.status_code == 200
        assert "PDF 版本与附件" in files.text
        assert revision.original_name in files.text
        assert f'action="/items/{item.id}/pdf' in files.text

        organize = client.get(f"/items/{item.id}/organize")
        assert organize.status_code == 200
        assert "标签与项目" in organize.text

        created = client.post(
            f"/documents/{item.id}/annotations",
            headers={"X-CSRF-Token": "test-csrf"},
            json={
                "revision_id": revision.id,
                "kind": "highlight",
                "scope": "private",
                "color": "yellow",
                "selected_text": "A useful result",
                "segments": [
                    {
                        "page_index": 0,
                        "quad_points": [10, 20, 30, 20, 10, 10, 30, 10],
                    }
                ],
            },
        )
        assert created.status_code == 201
        annotations = client.get(f"/items/{item.id}/annotations")
        assert annotations.status_code == 200
        assert "笔记与批注" in annotations.text
        assert "A useful result" in annotations.text
        assert "第 1 页" in annotations.text

        discussion = client.get(f"/items/{item.id}/discussion")
        assert discussion.status_code == 200
        assert "团队讨论" in discussion.text
        assert f'action="/items/{item.id}/discussion' in discussion.text

        assert client.get(f"/items/{item.id}/unknown").status_code == 404
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_project_editor_can_edit_item_without_seeing_permanent_delete(db, tmp_path, monkeypatch):
    owner_client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    editor = User(username="workspace-editor", password_hash="unused")
    project = Project(name="Shared editing", created_by=item.created_by)
    db.add_all([editor, project])
    db.flush()
    db.add_all([
        ProjectItem(project_id=project.id, item_id=item.id),
        ProjectMember(project_id=project.id, user_id=editor.id, role="editor"),
        LoginSession(
            token_hash=token_hash("editor-session"),
            csrf_token="editor-csrf",
            user_id=editor.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    ])
    db.commit()

    try:
        owner_page = owner_client.get(f"/items/{item.id}")
        assert "删除条目" in owner_page.text

        editor_client = TestClient(app, headers={"Accept-Language": "zh-CN,zh;q=0.9"})
        editor_client.cookies.set(get_settings().session_cookie, "editor-session")
        editor_page = editor_client.get(f"/items/{item.id}")
        assert editor_page.status_code == 200
        assert "编辑元数据" in editor_page.text
        assert "删除条目" not in editor_page.text

        view = open_item_workspace(db, editor, item.id, WorkspaceSection.summary)
        assert view.can_edit is True
        assert view.can_delete is False
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_item_citation_export_and_project_removal(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        project = Project(name="Focused review", created_by=item.created_by)
        db.add(project)
        db.flush()
        db.add_all([
            ProjectMember(project_id=project.id, user_id=item.created_by, role="owner"),
            ProjectItem(project_id=project.id, item_id=item.id),
        ])
        db.commit()

        exported = client.get(f"/documents/{item.id}/citation?file_format=bibtex")
        assert exported.status_code == 200
        assert item.title in exported.text
        assert "quirebase-export.bib" in exported.headers["content-disposition"]

        cited = client.get(f"/documents/{item.id}/citation?file_format=csl&style=apa")
        assert cited.status_code == 200
        assert item.title in cited.text
        assert "quirebase-citations.txt" in cited.headers["content-disposition"]

        plain_download = client.get(f"/items/{item.id}/download")
        assert "Paper-pdfs.zip" in plain_download.headers["content-disposition"]
        annotated_download = client.get(f"/items/{item.id}/download?include_annotations=true")
        assert "Paper-annotated-pdfs.zip" in annotated_download.headers["content-disposition"]

        removed = client.post(
            f"/items/{item.id}/projects/{project.id}/remove?csrf_token=test-csrf",
            follow_redirects=False,
        )
        assert removed.status_code == 303
        assert removed.headers["location"] == f"/items/{item.id}/organize"
        assert db.get(ProjectItem, (project.id, item.id)) is None
        assert db.query(AuditEvent).filter_by(action="project.item.remove", target_id=item.id).one()
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_item_summary_reports_exact_activity_counts(db, tmp_path, monkeypatch):
    _client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        user = db.get(User, item.created_by)
        db.add_all([
            Attachment(
                item_id=item.id,
                object_key="attachments/supplement.txt",
                sha256="a" * 64,
                size=12,
                mime_type="text/plain",
                original_name="supplement.txt",
                created_by=user.id,
            ),
            DiscussionMessage(item_id=item.id, author_id=user.id, body="First"),
            DiscussionMessage(item_id=item.id, author_id=user.id, body="Second"),
            PdfAnnotation(
                file_revision_id=revision.id,
                author_id=user.id,
                kind="highlight",
                scope="private",
                color="yellow",
            ),
            PdfAnnotation(
                file_revision_id=revision.id,
                author_id=user.id,
                kind="note",
                scope="private",
                color="blue",
            ),
        ])
        db.commit()

        data = open_item_workspace(db, user, item.id, WorkspaceSection.summary)

        assert data.revision_count == 1
        assert data.attachment_count == 1
        assert data.annotation_count == 2
        assert data.message_count == 2
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_item_header_keeps_pdf_link_on_lightweight_sections(db, tmp_path, monkeypatch):
    client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        for section in ("organize", "discussion"):
            response = client.get(f"/items/{item.id}/{section}")
            assert response.status_code == 200
            assert f"/items/{item.id}/pdf/{revision.id}" in response.text
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
