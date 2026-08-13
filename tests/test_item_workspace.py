from __future__ import annotations

from test_http import authenticated_client

from quirebase.app import app
from quirebase.config import get_settings
from quirebase.models import AuditEvent, Project, ProjectItem, ProjectMember


def test_item_workspace_separates_page_responsibilities(db, tmp_path, monkeypatch):
    client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        summary = client.get(f"/items/{item.id}")
        assert summary.status_code == 200
        assert 'aria-current="page"><span>⌂</span>' in summary.text
        assert "摘要与关键信息" in summary.text
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
