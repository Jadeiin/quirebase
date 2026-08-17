from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pymupdf
from test_http import authenticated_client

from quirebase.core.config import get_settings
from quirebase.discovery.lookup import MetadataNotFoundError
from quirebase.models import Item, ItemRead, ItemTag, Project, ProjectItem, ProjectMember, Tag, User
from quirebase.web.app import app


def pdf_bytes() -> bytes:
    document = pymupdf.open()
    document.new_page()
    contents = document.tobytes()
    document.close()
    return contents


def published_pdf_bytes() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "https://doi.org/10.1000/published")
    contents = document.tobytes()
    document.close()
    return contents


def test_dashboard_sidebar_limits_and_recent_reading(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        baseline = datetime(2026, 1, 1, tzinfo=UTC)
        for number in range(12):
            db.add(
                Item(
                    title=f"Dashboard paper {number}",
                    created_by=item.created_by,
                    created_at=baseline + timedelta(days=number),
                )
            )
        db.commit()

        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert 'lang="zh-CN"' in dashboard.text
        assert "主导航" in dashboard.text
        assert "Source code" not in dashboard.text
        assert dashboard.text.count('class="paper-row"') == 10
        assert "Dashboard paper 11" in dashboard.text
        assert "Dashboard paper 0" not in dashboard.text

        opened = client.get(f"/items/{item.id}")
        assert opened.status_code == 200
        assert db.get(ItemRead, (item.created_by, item.id)) is not None
        refreshed = client.get("/")
        assert "最近阅读" in refreshed.text
        assert item.title in refreshed.text
        assert client.get("/source").status_code == 404
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_item_page_validates_access_before_recording_read(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    other_user = User(username="private-owner", password_hash="unused")
    db.add(other_user)
    db.flush()
    private_item = Item(title="Private paper", created_by=other_user.id)
    db.add(private_item)
    db.commit()

    assert client.get("/items/missing-item").status_code == 404
    assert client.get(f"/items/{private_item.id}").status_code == 404
    assert db.get(ItemRead, (item.created_by, "missing-item")) is None
    assert db.get(ItemRead, (item.created_by, private_item.id)) is None


def test_library_pagination_filters_and_bulk_actions(db, tmp_path, monkeypatch):
    client, original, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        project = Project(name="Review project", created_by=original.created_by)
        second_project = Project(name="Reading queue", created_by=original.created_by)
        tag = Tag(name="Methods", created_by=original.created_by)
        db.add_all([project, second_project, tag])
        db.flush()
        db.add_all([
            ProjectMember(project_id=project.id, user_id=original.created_by, role="owner"),
            ProjectMember(project_id=second_project.id, user_id=original.created_by, role="editor"),
        ])
        selected = []
        for number in range(30):
            item = Item(
                title=f"Library paper {number:02d}",
                authors="Alice Researcher" if number % 2 == 0 else "Bob Scientist",
                keywords="imaging" if number % 3 == 0 else "simulation",
                publication_date="2025" if number % 2 == 0 else "2024",
                created_by=original.created_by,
                updated_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=number),
            )
            db.add(item)
            db.flush()
            if number < 2:
                selected.append(item)
                db.add_all([
                    ItemTag(item_id=item.id, tag_id=tag.id),
                    ProjectItem(project_id=project.id, item_id=item.id),
                ])
        db.commit()

        first_page = client.get("/library")
        assert first_page.status_code == 200
        assert "第 1 页" in first_page.text
        assert "共 2 页" in first_page.text
        assert "Library paper 29" in first_page.text
        second_page = client.get("/library?page=2")
        assert second_page.status_code == 200
        assert "Library paper 00" in second_page.text

        filtered = client.get("/library?author=Alice&year=2025&keyword=imaging")
        assert filtered.status_code == 200
        assert "Library paper 00" in filtered.text
        assert "Library paper 02" not in filtered.text
        project_filter = client.get(f"/library?project={project.id}&tag={tag.id}")
        assert "Library paper 00" in project_filter.text
        assert "Library paper 02" not in project_filter.text

        tagged = client.post(
            "/library/bulk?csrf_token=test-csrf",
            data={"action": "add_tag", "tag_name": "Priority", "item_ids": selected[0].id},
            follow_redirects=False,
        )
        assert tagged.status_code == 303
        priority = db.query(Tag).filter_by(name="Priority").one()
        assert db.get(ItemTag, (selected[0].id, priority.id)) is not None

        assigned = client.post(
            "/library/bulk?csrf_token=test-csrf",
            data={
                "action": "add_project",
                "project_id": second_project.id,
                "item_ids": [selected[0].id, selected[1].id],
            },
            follow_redirects=False,
        )
        assert assigned.status_code == 303
        assert db.get(ProjectItem, (second_project.id, selected[0].id)) is not None
        assert db.get(ProjectItem, (second_project.id, selected[1].id)) is not None

        exported = client.post(
            "/library/bulk?csrf_token=test-csrf",
            data={
                "action": "export_endnote",
                "item_ids": [selected[0].id, selected[1].id],
            },
        )
        assert exported.status_code == 200
        assert "quirebase-export.enw" in exported.headers["content-disposition"]
        assert "Library paper 00" in exported.text

        pdf_archive = client.post(
            "/library/bulk?csrf_token=test-csrf",
            data={"action": "download_pdfs", "item_ids": original.id},
        )
        assert pdf_archive.status_code == 200
        assert pdf_archive.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(pdf_archive.content)) as archive:
            assert archive.namelist() == ["paper.pdf"]

        deleted = client.post(
            "/library/bulk?csrf_token=test-csrf",
            data={
                "action": "delete_items",
                "item_ids": selected[1].id,
                "confirm_delete": "delete",
            },
            follow_redirects=False,
        )
        assert deleted.status_code == 303
        assert db.get(Item, selected[1].id) is None
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_pdf_import_modules(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        import_page = client.get("/bibliography/import")
        assert import_page.status_code == 200
        assert "通过标识符导入" in import_page.text
        assert "文献记录文件" in import_page.text
        assert "已发表 PDF" in import_page.text
        assert "未发表 PDF" in import_page.text
        assert "IEEE Xplore" in import_page.text

        uploaded = client.post(
            "/imports/pdf/unpublished?csrf_token=test-csrf",
            data={
                "title": "Working manuscript",
                "authors": "A. Author",
                "keywords": "draft; methods",
            },
            files={"pdf": ("draft.pdf", BytesIO(pdf_bytes()), "application/pdf")},
            follow_redirects=False,
        )
        assert uploaded.status_code == 303
        manuscript = db.query(Item).filter_by(title="Working manuscript").one()
        assert manuscript.reference_type == "unpublished"
        assert manuscript.revisions[0].original_name == "draft.pdf"

        monkeypatch.setattr(
            "quirebase.discovery.imports.lookup_metadata",
            lambda _identifier, _provider, *args, **kwargs: (
                object(),
                {
                    "title": "Published article",
                    "doi": "10.1000/published",
                    "authors": "P. Author",
                },
            ),
        )
        published = client.post(
            "/imports/pdf/published?csrf_token=test-csrf",
            files={"pdf": ("published.pdf", BytesIO(published_pdf_bytes()), "application/pdf")},
            follow_redirects=False,
        )
        assert published.status_code == 303
        article = db.query(Item).filter_by(title="Published article").one()
        assert article.doi == "10.1000/published"
        assert article.revisions[0].original_name == "published.pdf"
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_failed_published_pdf_import_removes_unreferenced_object(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    objects_before = set(get_settings().object_dir.rglob("*.pdf"))
    monkeypatch.setattr(
        "quirebase.discovery.imports.lookup_metadata",
        lambda _identifier, _provider, *args, **kwargs: (_ for _ in ()).throw(
            MetadataNotFoundError("metadata not found")
        ),
    )
    try:
        response = client.post(
            "/imports/pdf/published?csrf_token=test-csrf",
            data={"doi": "10.1000/missing"},
            files={"pdf": ("missing.pdf", BytesIO(pdf_bytes()), "application/pdf")},
        )

        assert response.status_code == 404
        assert set(get_settings().object_dir.rglob("*.pdf")) == objects_before
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
