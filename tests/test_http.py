import json
import re
from datetime import UTC, datetime, timedelta
from html import unescape
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.database import get_db
from quirebase.core.errors import VersionConflict
from quirebase.core.storage import LocalObjectStore
from quirebase.documents.bundles import export_revision_pdf
from quirebase.library import ItemMetadata, request_item_tag_recommendation, revise_item_metadata
from quirebase.models import (
    Attachment,
    AuditEvent,
    FileRevision,
    Item,
    ItemTagRecommendation,
    Job,
    LoginSession,
    Project,
    ProjectItem,
    ProjectMember,
    User,
)
from quirebase.search import search_index
from quirebase.web.app import app


def authenticated_client(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    user = User(username="reader", password_hash="unused")
    db.add(user)
    db.flush()
    raw = "test-session-token"
    login = LoginSession(
        token_hash=token_hash(raw),
        csrf_token="test-csrf",
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    item = Item(title="Paper", created_by=user.id)
    db.add_all([login, item])
    db.flush()
    key, digest, size = LocalObjectStore().put_pdf(
        source=BytesIO(b"%PDF-1.4\ntest"),
        maximum=100,
    )
    revision = FileRevision(
        item_id=item.id,
        object_key=key,
        sha256=digest,
        size=size,
        original_name="paper.pdf",
        page_count=1,
        page_geometry=json.dumps([[0, 0, 300, 400]]),
        processing_state="ready",
        created_by=user.id,
    )
    db.add(revision)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app, headers={"Accept-Language": "zh-CN,zh;q=0.9"})
    client.cookies.set(get_settings().session_cookie, raw)
    return client, item, revision


def test_pdf_range_and_annotation_api(db, tmp_path, monkeypatch):
    client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        viewer = client.get(f"/items/{item.id}/pdf/{revision.id}")
        assert viewer.status_code == 200
        assert 'lang="zh-CN"' in viewer.text
        assert "删除所选批注" in viewer.text
        encoded_messages = re.search(r'data-i18n="([^"]+)"', viewer.text)
        assert encoded_messages is not None
        messages = json.loads(unescape(encoded_messages.group(1)))
        assert messages["selectOwnAnnotation"] == "请选择一条你创建的批注。"

        content = client.get(
            f"/documents/{item.id}/revisions/{revision.id}/content",
            headers={"Range": "bytes=0-4"},
        )
        assert content.status_code == 206
        assert content.content == b"%PDF-"
        assert content.headers["content-range"].startswith("bytes 0-4/")

        created = client.post(
            f"/documents/{item.id}/annotations",
            headers={"X-CSRF-Token": "test-csrf"},
            json={
                "revision_id": revision.id,
                "kind": "highlight",
                "scope": "private",
                "color": "yellow",
                "selected_text": "test",
                "segments": [
                    {
                        "page_index": 0,
                        "quad_points": [10, 20, 30, 20, 10, 10, 30, 10],
                    }
                ],
            },
        )
        assert created.status_code == 201
        annotation = created.json()
        assert annotation["mine"] is True

        other_item = Item(title="Different paper", created_by=item.created_by)
        db.add(other_item)
        db.commit()
        mismatched = client.get(f"/documents/{other_item.id}/revisions/{revision.id}/export")
        assert mismatched.status_code == 404

        revision.original_name = "论文.pdf"
        db.commit()
        unicode_content = client.get(
            f"/documents/{item.id}/revisions/{revision.id}/content"
        )
        unicode_range = client.get(
            f"/documents/{item.id}/revisions/{revision.id}/content",
            headers={"Range": "bytes=0-4"},
        )
        unicode_download = client.get(
            f"/documents/{item.id}/revisions/{revision.id}/export",
            params={"include_annotations": False},
        )
        assert unicode_content.status_code == 200
        assert unicode_range.status_code == 206
        assert unicode_download.status_code == 200
        for response in (unicode_content, unicode_range, unicode_download):
            assert (
                "filename*=utf-8''%E8%AE%BA%E6%96%87.pdf"
                in response.headers["content-disposition"]
            )
        revision.original_name = "paper.pdf"
        db.commit()

        exported_paths = []
        exported_timezones = []

        def fake_export_annotations(source, target, annotations, author_names, **kwargs):
            target.write_bytes(source.read_bytes())
            exported_paths.append(target)
            exported_timezones.append(kwargs.get("display_timezone"))

        monkeypatch.setattr(
            "quirebase.documents.bundles.export_annotations",
            fake_export_annotations,
        )
        project = Project(name="Current revision export", created_by=item.created_by)
        db.add(project)
        db.flush()
        db.add_all([
            ProjectMember(project_id=project.id, user_id=item.created_by, role="owner"),
            ProjectItem(project_id=project.id, item_id=item.id),
        ])
        db.commit()
        exported = client.get(
            f"/documents/{item.id}/revisions/{revision.id}/export",
            params={
                "include_annotations": True,
                "project_id": project.id,
                "timezone": "Asia/Shanghai",
            },
        )
        assert exported.status_code == 200
        assert "paper-annotated.pdf" in exported.headers["content-disposition"]
        assert len(exported_paths) == 1
        assert not exported_paths[0].exists()
        assert str(exported_timezones[0]) == "Asia/Shanghai"
        events = (
            db
            .query(AuditEvent)
            .filter_by(action="item.download_revision_pdf", target_id=revision.id)
            .all()
        )
        details = [json.loads(event.detail) for event in events]
        assert {
            "item_id": item.id,
            "include_annotations": True,
            "project_id": project.id,
        } in details
        assert all(event.actor_id == item.created_by for event in events)

        failed_export_paths = []

        def failing_export_annotations(source, target, annotations, author_names, **kwargs):
            failed_export_paths.append(target)
            raise RuntimeError("annotation export failed")

        monkeypatch.setattr(
            "quirebase.documents.bundles.export_annotations",
            failing_export_annotations,
        )
        with pytest.raises(RuntimeError, match="annotation export failed"):
            client.get(
                f"/documents/{item.id}/revisions/{revision.id}/export",
                params={"include_annotations": True},
            )
        assert len(failed_export_paths) == 1
        assert not failed_export_paths[0].exists()

        monkeypatch.setattr(
            "quirebase.documents.bundles.export_annotations",
            fake_export_annotations,
        )

        def failing_record(*args, **kwargs):
            raise RuntimeError("audit recording failed")

        monkeypatch.setattr(
            "quirebase.documents.bundles._record_revision_pdf_export",
            failing_record,
        )
        exported_paths.clear()
        user = db.get(User, item.created_by)
        with pytest.raises(RuntimeError, match="audit recording failed"):
            export_revision_pdf(
                db,
                user,
                item.id,
                revision.id,
                include_annotations=True,
            )
        assert len(exported_paths) == 1
        assert not exported_paths[0].exists()

        underlined = client.post(
            f"/documents/{item.id}/annotations",
            headers={"X-CSRF-Token": "test-csrf"},
            json={
                "revision_id": revision.id,
                "kind": "underline",
                "scope": "private",
                "color": "red",
                "selected_text": "underlined text",
                "body": "underline comment",
                "segments": [
                    {
                        "page_index": 0,
                        "quad_points": [10, 20, 30, 20, 10, 10, 30, 10],
                    }
                ],
            },
        )
        assert underlined.status_code == 201
        assert underlined.json()["kind"] == "underline"
        assert underlined.json()["color"] == "red"

        conflict = client.patch(
            f"/documents/{item.id}/annotations/{annotation['id']}",
            headers={"X-CSRF-Token": "test-csrf"},
            json={"version": 99, "color": "red"},
        )
        assert conflict.status_code == 409

        deleted = client.delete(
            f"/documents/{item.id}/annotations/{annotation['id']}",
            headers={"X-CSRF-Token": "test-csrf"},
        )
        assert deleted.status_code == 204
        assert deleted.content == b""
        assert (
            db
            .query(AuditEvent)
            .filter_by(action="annotation.delete", target_id=annotation["id"])
            .one()
        )
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_item_overview_uses_the_ready_revision_thumbnail(db, tmp_path, monkeypatch):
    client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    thumbnail = get_settings().object_dir / "thumbnails" / f"{revision.id}.png"
    thumbnail.parent.mkdir(parents=True, exist_ok=True)
    thumbnail.write_bytes(b"\x89PNG\r\n\x1a\nthumbnail")
    thumbnail_url = f"/documents/{item.id}/thumbnail"

    try:
        overview = client.get(f"/items/{item.id}")
        response = client.get(thumbnail_url)

        assert f'src="{thumbnail_url}"' in overview.text
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == thumbnail.read_bytes()
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_item_overview_omits_a_missing_thumbnail(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    thumbnail_url = f"/documents/{item.id}/thumbnail"

    try:
        overview = client.get(f"/items/{item.id}")

        assert thumbnail_url not in overview.text
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_deleting_latest_pdf_revision_removes_its_files_and_falls_back_thumbnail(
    db, tmp_path, monkeypatch
):
    client, item, old_revision = authenticated_client(db, tmp_path, monkeypatch)
    store = LocalObjectStore()
    old_thumbnail = get_settings().object_dir / "thumbnails" / f"{old_revision.id}.png"
    old_thumbnail.parent.mkdir(parents=True, exist_ok=True)
    old_thumbnail.write_bytes(b"old-thumbnail")
    old_revision.full_text = "fallbacksearchtoken"
    key, digest, size = store.put_pdf(BytesIO(b"%PDF-1.4\nnewer"), maximum=100)
    new_revision = FileRevision(
        item_id=item.id,
        object_key=key,
        sha256=digest,
        size=size,
        original_name="newer.pdf",
        page_count=1,
        page_geometry="[[0,0,300,400]]",
        processing_state="ready",
        full_text="deletedsearchtoken",
        created_by=item.created_by,
        created_at=old_revision.created_at + timedelta(seconds=1),
    )
    db.add(new_revision)
    db.commit()
    new_object = store.path(key)
    new_thumbnail = get_settings().object_dir / "thumbnails" / f"{new_revision.id}.png"
    new_thumbnail.write_bytes(b"new-thumbnail")
    thumbnail_url = f"/documents/{item.id}/thumbnail"
    index = search_index(db)
    index.index_item(db, item.id)
    recommendation = request_item_tag_recommendation(
        db, item.id, owner_id=item.created_by
    )
    previous_fingerprint = recommendation.input_fingerprint
    previous_generation = recommendation.generation_token
    db.commit()

    try:
        assert client.get(thumbnail_url).content == b"new-thumbnail"
        assert index.search(db, "deletedsearchtoken") == [item.id]

        deleted = client.post(
            f"/items/{item.id}/pdf/{new_revision.id}/delete",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )

        assert deleted.status_code == 303
        assert deleted.headers["location"] == f"/items/{item.id}/files"
        assert db.get(FileRevision, new_revision.id) is None
        assert not new_object.exists()
        assert not new_thumbnail.exists()
        assert client.get(thumbnail_url).content == b"old-thumbnail"
        assert index.search(db, "deletedsearchtoken") == []
        assert index.search(db, "fallbacksearchtoken") == [item.id]
        refreshed = db.scalar(
            select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item.id)
        )
        assert refreshed is not None
        assert refreshed.input_fingerprint != previous_fingerprint
        assert refreshed.generation_token == previous_generation + 1
        assert refreshed.generated_at is None
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_pdf_revision_cannot_be_deleted_while_inspection_is_running(
    db, tmp_path, monkeypatch
):
    client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    thumbnail = get_settings().object_dir / "thumbnails" / f"{revision.id}.png"
    thumbnail.parent.mkdir(parents=True, exist_ok=True)
    thumbnail.write_bytes(b"thumbnail")
    object_path = LocalObjectStore().path(revision.object_key)
    job = Job(
        kind="pdf.inspect",
        payload=json.dumps({"revision_id": revision.id}),
        idempotency_key=f"pdf.inspect:{revision.id}",
        owner_id=item.created_by,
        state="running",
        attempts=1,
    )
    db.add(job)
    db.commit()

    try:
        deleted = client.post(
            f"/items/{item.id}/pdf/{revision.id}/delete",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )

        assert deleted.status_code == 409
        assert db.get(FileRevision, revision.id) is not None
        assert db.get(Job, job.id) is not None
        assert object_path.exists()
        assert thumbnail.exists()
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_deleting_pdf_revision_cancels_pending_annotation_exports(db, tmp_path, monkeypatch):
    client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    job = Job(
        kind="pdf.export_annotations",
        payload=json.dumps({"revision_id": revision.id}),
        idempotency_key=f"pdf.export:test:{revision.id}:none:pending",
        owner_id=item.created_by,
        state="pending",
    )
    db.add(job)
    db.commit()

    try:
        deleted = client.post(
            f"/items/{item.id}/pdf/{revision.id}/delete",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )

        assert deleted.status_code == 303
        assert db.get(FileRevision, revision.id) is None
        assert db.get(Job, job.id) is None
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_pdf_revision_cannot_be_deleted_while_annotation_export_is_running(
    db, tmp_path, monkeypatch
):
    client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    object_path = LocalObjectStore().path(revision.object_key)
    job = Job(
        kind="pdf.export_annotations",
        payload=json.dumps({"revision_id": revision.id}),
        idempotency_key=f"pdf.export:test:{revision.id}:none:running",
        owner_id=item.created_by,
        state="running",
        attempts=1,
    )
    db.add(job)
    db.commit()

    try:
        deleted = client.post(
            f"/items/{item.id}/pdf/{revision.id}/delete",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )

        assert deleted.status_code == 409
        assert db.get(FileRevision, revision.id) is not None
        assert db.get(Job, job.id) is not None
        assert object_path.exists()
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_graphical_abstract_attachment_overrides_the_pdf_thumbnail(db, tmp_path, monkeypatch):
    client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    pdf_thumbnail = get_settings().object_dir / "thumbnails" / f"{revision.id}.png"
    pdf_thumbnail.parent.mkdir(parents=True, exist_ok=True)
    pdf_thumbnail.write_bytes(b"pdf-thumbnail")

    try:
        uploaded = client.post(
            f"/items/{item.id}/attachments",
            data={"csrf_token": "test-csrf", "graphical_abstract": "true"},
            files={"attachment": ("abstract.png", b"\x89PNG\r\n\x1a\ngraphical", "image/png")},
            follow_redirects=False,
        )
        attachment = db.query(Attachment).filter_by(item_id=item.id).one()

        assert uploaded.status_code == 303
        assert attachment.role == "graphical_abstract"
        assert client.get(f"/documents/{item.id}/thumbnail").content.endswith(b"graphical")
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_graphical_abstract_rejects_content_that_is_not_an_image(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)

    try:
        uploaded = client.post(
            f"/items/{item.id}/attachments",
            data={"csrf_token": "test-csrf", "graphical_abstract": "true"},
            files={"attachment": ("abstract.png", b"not really a png", "image/png")},
            follow_redirects=False,
        )

        assert uploaded.status_code == 422
        assert db.query(Attachment).filter_by(item_id=item.id).count() == 0
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_regular_attachment_accepts_non_image_content(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)

    try:
        uploaded = client.post(
            f"/items/{item.id}/attachments",
            data={"csrf_token": "test-csrf"},
            files={"attachment": ("dataset.csv", b"column\nvalue\n", "text/csv")},
            follow_redirects=False,
        )
        attachment = db.query(Attachment).filter_by(item_id=item.id).one()

        assert uploaded.status_code == 303
        assert attachment.mime_type == "text/csv"
        assert attachment.role is None
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_replacing_and_deleting_graphical_abstract_preserves_attachment_and_falls_back(
    db, tmp_path, monkeypatch
):
    client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    pdf_thumbnail = get_settings().object_dir / "thumbnails" / f"{revision.id}.png"
    pdf_thumbnail.parent.mkdir(parents=True, exist_ok=True)
    pdf_thumbnail.write_bytes(b"pdf-thumbnail")

    try:
        for name, content in (("first.png", b"first-image"), ("second.png", b"second-image")):
            response = client.post(
                f"/items/{item.id}/attachments",
                data={"csrf_token": "test-csrf", "graphical_abstract": "true"},
                files={"attachment": (name, b"\x89PNG\r\n\x1a\n" + content, "image/png")},
                follow_redirects=False,
            )
            assert response.status_code == 303

        first, second = db.query(Attachment).filter_by(item_id=item.id).order_by(Attachment.created_at)
        second_object = LocalObjectStore().path(second.object_key)
        assert first.role is None
        assert second.role == "graphical_abstract"
        assert client.get(f"/documents/{item.id}/thumbnail").content.endswith(b"second-image")

        deleted = client.post(
            f"/items/{item.id}/attachments/{second.id}/delete",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )

        assert deleted.status_code == 303
        assert db.get(Attachment, first.id) is not None
        assert db.get(Attachment, second.id) is None
        assert not second_object.exists()
        assert client.get(f"/documents/{item.id}/thumbnail").content == b"pdf-thumbnail"
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_item_edit_detects_conflicts_and_updates_search(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        updated = client.post(
            f"/items/{item.id}/edit",
            data={
                "csrf_token": "test-csrf",
                "version": 1,
                "title": "Revised Paper",
                "abstract": "Quantum transport",
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303
        db.refresh(item)
        assert item.version == 2
        assert item.title == "Revised Paper"

        results = client.get("/?q=quantum")
        assert results.status_code == 200
        assert "Revised Paper" in results.text

        stale = client.post(
            f"/items/{item.id}/edit",
            data={"csrf_token": "test-csrf", "version": 1, "title": "Lost update"},
        )
        assert stale.status_code == 409
        db.refresh(item)
        assert item.title == "Revised Paper"
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_item_edit_uses_atomic_optimistic_lock(db):
    owner = User(username="concurrent_owner", password_hash="unused")
    db.add(owner)
    db.flush()
    item = Item(title="Original", created_by=owner.id)
    db.add(item)
    db.commit()

    with (
        Session(db.bind, expire_on_commit=False) as first,
        Session(db.bind, expire_on_commit=False) as second,
    ):
        first_owner = first.get(User, owner.id)
        second_owner = second.get(User, owner.id)
        first_item = first.get(Item, item.id)
        second_item = second.get(Item, item.id)
        assert first_owner and second_owner and first_item and second_item
        assert first_item.version == second_item.version == 1

        revise_item_metadata(
            first,
            first_owner,
            item.id,
            first_item.version,
            ItemMetadata(title="First update"),
        )
        with pytest.raises(VersionConflict):
            revise_item_metadata(
                second,
                second_owner,
                item.id,
                second_item.version,
                ItemMetadata(title="Lost update"),
            )
    db.expire_all()
    assert db.get(Item, item.id).title == "First update"
