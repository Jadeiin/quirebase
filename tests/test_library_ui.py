from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pymupdf
from inquiro import CandidateRecord, Identifier
from sqlalchemy.orm import Session
from test_http import authenticated_client

from quirebase.core.config import get_settings
from quirebase.core.storage import LocalObjectStore
from quirebase.documents.revisions import delete_unreferenced_objects, stage_pdf
from quirebase.models import (
    ImportBatch,
    Item,
    ItemRead,
    ItemTag,
    Project,
    ProjectItem,
    ProjectMember,
    Tag,
    User,
)
from quirebase.web.app import app


def provider_candidate(identifier: str, title: str, *, authors: str | None = None):
    return CandidateRecord(
        provider="crossref",
        identifier=Identifier("doi", identifier),
        title=title,
        authors=authors,
        doi=identifier,
        identifiers=(Identifier("doi", identifier),),
    )


def pdf_bytes() -> bytes:
    document = pymupdf.open()
    document.new_page()
    contents = document.tobytes()
    document.close()
    return contents


def published_pdf_bytes(doi: str = "10.1000/published") -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), f"https://doi.org/{doi}")
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
                abstract="This abstract should be optional." if number == 0 else None,
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
        assert 'x-model="styleQuery"' in first_page.text
        assert 'x-for="citationStyle in citationStyles"' in first_page.text
        assert 'x-model="style"' in first_page.text
        assert 'name="tag_name"' in first_page.text
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
        assert "This abstract should be optional." in exported.text

        native_checkbox_export = client.post(
            "/library/bulk?csrf_token=test-csrf",
            data={
                "action": "export_endnote",
                "item_ids": selected[0].id,
                "include_abstract": ["false", "true"],
            },
        )
        assert native_checkbox_export.status_code == 200
        assert "This abstract should be optional." in native_checkbox_export.text

        exported_without_abstract = client.post(
            "/library/bulk?csrf_token=test-csrf",
            data={
                "action": "export_endnote",
                "item_ids": selected[0].id,
                "include_abstract": "false",
            },
        )
        assert exported_without_abstract.status_code == 200
        assert "This abstract should be optional." not in exported_without_abstract.text

        pdf_archive = client.post(
            "/library/bulk?csrf_token=test-csrf",
            data={"action": "download_pdfs", "item_ids": original.id},
        )
        assert pdf_archive.status_code == 200
        assert pdf_archive.headers["content-type"] == "application/zip"
        assert "quirebase-selected-pdfs.zip" in pdf_archive.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(pdf_archive.content)) as archive:
            assert archive.namelist() == [
                "Paper/Paper-pdf-v01-paper.pdf",
                "Paper/manifest.json",
                "manifest.json",
            ]

        annotated_pdf_archive = client.post(
            "/library/bulk?csrf_token=test-csrf",
            data={
                "action": "download_pdfs",
                "item_ids": original.id,
                "include_annotations": "true",
            },
        )
        assert annotated_pdf_archive.status_code == 200
        assert (
            "quirebase-selected-annotated-pdfs.zip"
            in annotated_pdf_archive.headers["content-disposition"]
        )

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


def test_pdf_import_batch_previews_before_creating_items(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        import_page = client.get("/bibliography/import")
        assert import_page.status_code == 200
        assert "通过标识符导入" in import_page.text
        assert "文献记录文件" in import_page.text
        assert "已发表 PDF" in import_page.text
        assert 'data-method="manual"' in import_page.text
        assert "IEEE Xplore" in import_page.text

        monkeypatch.setattr(
            "quirebase.library.imports.lookup_candidate",
            lambda identifier, _provider, _settings: provider_candidate(
                identifier,
                f"Article {identifier.rsplit('/', 1)[-1]}",
                authors="P. Author",
            ),
        )
        preview = client.post(
            "/imports/pdf/published?csrf_token=test-csrf",
            files=[
                (
                    "pdfs",
                    ("first.pdf", BytesIO(published_pdf_bytes("10.1000/first")), "application/pdf"),
                ),
                (
                    "pdfs",
                    (
                        "second.pdf",
                        BytesIO(published_pdf_bytes("10.1000/second")),
                        "application/pdf",
                    ),
                ),
            ],
        )
        assert preview.status_code == 200
        assert "first.pdf" in preview.text
        assert "second.pdf" in preview.text
        assert db.query(Item).filter(Item.title.like("Article %")).count() == 0

        batch = db.query(ImportBatch).filter_by(file_format="pdf").one()
        assert f"/bibliography/import/{batch.id}" in preview.text

        committed = client.post(
            f"/bibliography/import/{batch.id}?csrf_token=test-csrf", follow_redirects=False
        )
        assert committed.status_code == 303
        first = db.query(Item).filter_by(doi="10.1000/first").one()
        second = db.query(Item).filter_by(doi="10.1000/second").one()
        assert first.revisions[0].original_name == "first.pdf"
        assert second.revisions[0].original_name == "second.pdf"
        assert db.get(ImportBatch, batch.id) is None
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_pdf_import_batch_keeps_successes_and_reports_failed_files(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    objects_before = set(get_settings().object_dir.rglob("*.pdf"))
    monkeypatch.setattr(
        "quirebase.library.imports.lookup_candidate",
        lambda identifier, _provider, _settings: provider_candidate(
            identifier, "Importable article"
        ),
    )
    try:
        preview = client.post(
            "/imports/pdf/published?csrf_token=test-csrf",
            files=[
                (
                    "pdfs",
                    ("valid.pdf", BytesIO(published_pdf_bytes("10.1000/valid")), "application/pdf"),
                ),
                ("pdfs", ("missing-doi.pdf", BytesIO(pdf_bytes()), "application/pdf")),
            ],
        )
        assert preview.status_code == 200
        assert "valid.pdf" in preview.text
        assert "missing-doi.pdf" in preview.text
        batch = db.query(ImportBatch).filter_by(file_format="pdf").one()
        assert '"code": "missing_doi"' in batch.errors
        assert f"/bibliography/import/{batch.id}" in preview.text
        assert len(set(get_settings().object_dir.rglob("*.pdf")) - objects_before) == 1

        committed = client.post(
            f"/bibliography/import/{batch.id}?csrf_token=test-csrf", follow_redirects=False
        )
        assert committed.status_code == 303
        article = db.query(Item).filter_by(doi="10.1000/valid").one()
        assert article.revisions[0].original_name == "valid.pdf"
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_pdf_import_batch_rejects_an_accessible_duplicate_doi(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    item.doi = "10.1000/existing"
    db.commit()
    objects_before = set(get_settings().object_dir.rglob("*.pdf"))
    try:
        preview = client.post(
            "/imports/pdf/published?csrf_token=test-csrf",
            files=[
                (
                    "pdfs",
                    (
                        "duplicate.pdf",
                        BytesIO(published_pdf_bytes("10.1000/existing")),
                        "application/pdf",
                    ),
                )
            ],
        )
        assert preview.status_code == 200
        assert "duplicate.pdf" in preview.text
        batch = db.query(ImportBatch).filter_by(file_format="pdf").one()
        assert '"code": "existing_doi"' in batch.errors
        assert batch.records == "[]"
        assert f'action="/bibliography/import/{batch.id}?csrf_token=' not in preview.text
        assert set(get_settings().object_dir.rglob("*.pdf")) == objects_before
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_discard_pdf_import_batch_removes_staged_objects(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    objects_before = set(get_settings().object_dir.rglob("*.pdf"))
    monkeypatch.setattr(
        "quirebase.library.imports.lookup_candidate",
        lambda identifier, _provider, _settings: provider_candidate(
            identifier, "Discarded candidate"
        ),
    )
    try:
        preview = client.post(
            "/imports/pdf/published?csrf_token=test-csrf",
            files=[
                (
                    "pdfs",
                    (
                        "discard.pdf",
                        BytesIO(published_pdf_bytes("10.1000/discard")),
                        "application/pdf",
                    ),
                )
            ],
        )
        assert preview.status_code == 200
        batch = db.query(ImportBatch).filter_by(file_format="pdf").one()
        assert len(set(get_settings().object_dir.rglob("*.pdf")) - objects_before) == 1

        discarded = client.post(
            f"/bibliography/import/{batch.id}/discard?csrf_token=test-csrf",
            follow_redirects=False,
        )
        assert discarded.status_code == 303
        assert discarded.headers["location"] == "/bibliography/import"
        assert db.get(ImportBatch, batch.id) is None
        assert set(get_settings().object_dir.rglob("*.pdf")) == objects_before
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_discard_pdf_import_batch_preserves_object_used_by_another_batch(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    shared_pdf = published_pdf_bytes("10.1000/shared-staged")
    monkeypatch.setattr(
        "quirebase.library.imports.lookup_candidate",
        lambda identifier, _provider, _settings: provider_candidate(
            identifier, "Shared staged PDF"
        ),
    )
    try:
        for filename in ("first-copy.pdf", "second-copy.pdf"):
            preview = client.post(
                "/imports/pdf/published?csrf_token=test-csrf",
                files=[
                    (
                        "pdfs",
                        (
                            filename,
                            BytesIO(shared_pdf),
                            "application/pdf",
                        ),
                    )
                ],
            )
            assert preview.status_code == 200

        batches = db.query(ImportBatch).filter_by(file_format="pdf").all()
        assert len(batches) == 2
        first_pdf = json.loads(batches[0].records)[0]["_pdf"]
        second_pdf = json.loads(batches[1].records)[0]["_pdf"]
        assert first_pdf["object_key"] == second_pdf["object_key"]
        object_path = LocalObjectStore().path(first_pdf["object_key"])
        assert object_path.is_file()

        discarded = client.post(
            f"/bibliography/import/{batches[0].id}/discard?csrf_token=test-csrf",
            follow_redirects=False,
        )
        assert discarded.status_code == 303
        assert object_path.is_file()

        committed = client.post(
            f"/bibliography/import/{batches[1].id}?csrf_token=test-csrf",
            follow_redirects=False,
        )
        assert committed.status_code == 303
        imported = db.query(Item).filter_by(doi="10.1000/shared-staged").one()
        assert LocalObjectStore().path(imported.revisions[0].object_key).is_file()
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_cleanup_preserves_object_referenced_by_an_uncommitted_pdf_import_batch(
    db, tmp_path, monkeypatch
):
    _client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    pdf = published_pdf_bytes("10.1000/in-flight-staged")
    discarded = stage_pdf(
        BytesIO(pdf),
        "discarded-copy.pdf",
        100_000,
    )
    in_flight = stage_pdf(
        BytesIO(pdf),
        "in-flight.pdf",
        100_000,
    )
    assert discarded.object_key == in_flight.object_key
    object_path = LocalObjectStore().path(in_flight.object_key)
    batch = ImportBatch(
        owner_id=item.created_by,
        file_format="pdf",
        records=json.dumps([
            {
                "title": "In-flight staged PDF",
                "_pdf": {
                    "object_key": in_flight.object_key,
                    "sha256": in_flight.sha256,
                    "size": in_flight.size,
                    "original_name": in_flight.original_name,
                },
            }
        ]),
        errors="[]",
    )
    db.add(batch)
    db.flush()

    try:
        discarded.release()
        with Session(db.bind) as cleanup_db:
            assert delete_unreferenced_objects(cleanup_db, (discarded.object_key,)) == ()
        assert object_path.is_file()

        db.commit()
        in_flight.release()
        with Session(db.bind) as cleanup_db:
            assert delete_unreferenced_objects(cleanup_db, (in_flight.object_key,)) == ()
        assert object_path.is_file()
    finally:
        discarded.release()
        in_flight.release()
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_commit_pdf_import_batch_rechecks_doi_after_stale_preview(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    monkeypatch.setattr(
        "quirebase.library.imports.lookup_candidate",
        lambda identifier, _provider, _settings: provider_candidate(
            identifier, "Stale DOI candidate"
        ),
    )
    try:
        for filename in ("first-preview.pdf", "stale-preview.pdf"):
            preview = client.post(
                "/imports/pdf/published?csrf_token=test-csrf",
                files=[
                    (
                        "pdfs",
                        (
                            filename,
                            BytesIO(published_pdf_bytes("10.1000/stale-preview")),
                            "application/pdf",
                        ),
                    )
                ],
            )
            assert preview.status_code == 200

        batches = db.query(ImportBatch).filter_by(file_format="pdf").all()
        assert len(batches) == 2
        first = client.post(
            f"/bibliography/import/{batches[0].id}?csrf_token=test-csrf",
            follow_redirects=False,
        )
        assert first.status_code == 303

        stale = client.post(
            f"/bibliography/import/{batches[1].id}?csrf_token=test-csrf",
            follow_redirects=False,
        )
        assert stale.status_code == 409
        assert db.query(Item).filter_by(doi="10.1000/stale-preview").count() == 1
        assert db.get(ImportBatch, batches[1].id) is not None
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
