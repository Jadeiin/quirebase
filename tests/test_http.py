import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx2
import pytest
from sqlalchemy import func, select
from storage_helpers import local_object_path, put_pdf_object

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.database import get_db
from quirebase.core.errors import VersionConflict
from quirebase.core.storage import ObjectMetadata, ObjectResponse, ObjectSuffix, get_object_store
from quirebase.documents import create_attachment
from quirebase.documents import workflows as document_workflows
from quirebase.documents.bundles import export_revision_pdf
from quirebase.library import ItemMetadata, request_item_tag_recommendation, revise_item_metadata
from quirebase.models import (
    Attachment,
    AttachmentRole,
    AuditEvent,
    FileRevision,
    Item,
    ItemTagRecommendation,
    LoginSession,
    Project,
    ProjectItem,
    ProjectMember,
    User,
)
from quirebase.search import search_index
from quirebase.web.app import create_app


async def authenticated_async_client(db, session_factory, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    user = User(username="reader", password_hash="unused")
    db.add(user)
    await db.flush()
    raw = "test-session-token"
    login = LoginSession(
        token_hash=token_hash(raw),
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    item = Item(title="Paper", created_by=user.id)
    db.add_all([login, item])
    await db.flush()
    key, size = await put_pdf_object(b"%PDF-1.4\ntest", 100)
    revision = FileRevision(
        item_id=item.id,
        object_key=key,
        size=size,
        original_name="paper.pdf",
        page_count=1,
        page_geometry=json.dumps([[0, 0, 300, 400]]),
        processing_state="ready",
        created_by=user.id,
    )
    db.add(revision)
    await db.commit()

    test_app = create_app(mcp_session_factory=session_factory)

    async def override_db():
        await asyncio.sleep(0)
        yield db

    test_app.dependency_overrides[get_db] = override_db
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=test_app, raise_app_exceptions=False),
        base_url="http://testserver",
        headers={
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "http://testserver",
        },
        follow_redirects=True,
    )
    client.cookies.set(get_settings().session_cookie, raw)
    return client, item, revision


@pytest.mark.anyio
async def test_pdf_range_and_annotation_api(async_db, async_session_factory, tmp_path, monkeypatch):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        viewer = await client.get(f"/api/v1/items/{item.id}/revisions/{revision.id}/viewer")
        assert viewer.status_code == 200
        assert viewer.json()["revision"]["id"] == revision.id
        assert viewer.json()["revision"]["page_geometry"] == [[0, 0, 300, 400]]
        assert viewer.json()["editable"] is True
        assert viewer.json()["annotation_author"] == "reader"
        assert viewer.json()["revision"]["content_url"] == (
            f"/api/v1/items/{item.id}/revisions/{revision.id}/content"
        )

        content = await client.get(
            f"/api/v1/items/{item.id}/revisions/{revision.id}/content",
            headers={"Range": "bytes=0-4"},
        )
        assert content.status_code == 206
        assert content.content == b"%PDF-"
        assert content.headers["content-range"].startswith("bytes 0-4/")
        assert content.headers["etag"].startswith('"')
        assert content.headers["etag"].endswith('"')
        assert not content.headers["etag"].startswith('""')

        empty_range = await client.get(
            f"/api/v1/items/{item.id}/revisions/{revision.id}/content",
            headers={"Range": "bytes=-"},
        )
        assert empty_range.status_code == 416
        assert empty_range.headers["content-range"].startswith("bytes */")

        created = await client.post(
            f"/api/v1/items/{item.id}/annotations",
            headers={"X-CSRF-Token": "test-csrf"},
            json={
                "id": str(uuid4()),
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "highlight",
                "scope": "private",
                "selected_text": "test",
                "payload": {
                    "type": "highlight",
                    "rect": {"x": 10, "y": 10, "width": 20, "height": 10},
                    "style": {"stroke_color": "#FFEB33", "opacity": 0.35},
                    "segment_rects": [{"x": 10, "y": 10, "width": 20, "height": 10}],
                },
            },
        )
        assert created.status_code == 201
        annotation = created.json()
        assert annotation["mine"] is True
        assert annotation["replies"] == []

        reply_id = str(uuid4())
        replied = await client.post(
            f"/api/v1/items/{item.id}/annotations/{annotation['id']}/replies",
            headers={"X-CSRF-Token": "test-csrf"},
            json={"id": reply_id, "body": "Collaborative reply"},
        )
        assert replied.status_code == 201
        reply = replied.json()
        assert reply["annotation_id"] == annotation["id"]
        assert reply["body"] == "Collaborative reply"
        listed_with_reply = await client.get(
            f"/api/v1/items/{item.id}/annotations",
            params={"revision_id": revision.id},
        )
        listed_reply = listed_with_reply.json()[0]["replies"][0]
        assert listed_reply["id"] == reply["id"]
        assert listed_reply["body"] == reply["body"]
        updated_reply = await client.patch(
            f"/api/v1/items/{item.id}/annotations/{annotation['id']}/replies/{reply_id}",
            headers={"X-CSRF-Token": "test-csrf"},
            json={"version": reply["version"], "body": "Updated reply"},
        )
        assert updated_reply.status_code == 200
        assert updated_reply.json()["version"] == 2
        assert updated_reply.json()["body"] == "Updated reply"
        deleted_reply = await client.delete(
            f"/api/v1/items/{item.id}/annotations/{annotation['id']}/replies/{reply_id}",
            headers={"X-CSRF-Token": "test-csrf"},
            params={"version": 2},
        )
        assert deleted_reply.status_code == 200
        restored_reply = await client.post(
            f"/api/v1/items/{item.id}/annotations/{annotation['id']}/replies/{reply_id}/restore",
            headers={"X-CSRF-Token": "test-csrf"},
            params={"version": 3},
        )
        assert restored_reply.status_code == 200
        assert restored_reply.json()["version"] == 4
        deleted_reply_again = await client.delete(
            f"/api/v1/items/{item.id}/annotations/{annotation['id']}/replies/{reply_id}",
            headers={"X-CSRF-Token": "test-csrf"},
            params={"version": 4},
        )
        assert deleted_reply_again.status_code == 200

        duplicate = await client.post(
            f"/api/v1/items/{item.id}/annotations",
            headers={"X-CSRF-Token": "test-csrf"},
            json={
                "id": annotation["id"],
                "revision_id": revision.id,
                "page_index": annotation["page_index"],
                "kind": annotation["kind"],
                "scope": annotation["scope"],
                "project_id": annotation["project_id"],
                "body": annotation["body"],
                "selected_text": annotation["selected_text"],
                "payload": annotation["payload"],
            },
        )
        assert duplicate.status_code == 409

        other_item = Item(title="Different paper", created_by=item.created_by)
        db.add(other_item)
        await db.commit()
        mismatched = await client.get(
            f"/api/v1/items/{other_item.id}/revisions/{revision.id}/export"
        )
        assert mismatched.status_code == 404

        revision.original_name = "论文.pdf"
        await db.commit()
        unicode_content = await client.get(
            f"/api/v1/items/{item.id}/revisions/{revision.id}/content"
        )
        unicode_range = await client.get(
            f"/api/v1/items/{item.id}/revisions/{revision.id}/content",
            headers={"Range": "bytes=0-4"},
        )
        unicode_download = await client.get(
            f"/api/v1/items/{item.id}/revisions/{revision.id}/export",
            params={"include_annotations": False},
        )
        assert unicode_content.status_code == 200
        assert unicode_range.status_code == 206
        assert unicode_download.status_code == 200
        for response in (unicode_content, unicode_range, unicode_download):
            assert (
                "filename*=utf-8''%E8%AE%BA%E6%96%87.pdf" in response.headers["content-disposition"]
            )
        revision.original_name = "paper.pdf"
        await db.commit()

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
        await db.flush()
        db.add_all([
            ProjectMember(project_id=project.id, user_id=item.created_by, role="owner"),
            ProjectItem(project_id=project.id, item_id=item.id),
        ])
        await db.commit()
        exported = await client.get(
            f"/api/v1/items/{item.id}/revisions/{revision.id}/export",
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
        events = list(
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "item.download_revision_pdf",
                    AuditEvent.target_id == revision.id,
                )
            )
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
        failed_export = await client.get(
            f"/api/v1/items/{item.id}/revisions/{revision.id}/export",
            params={"include_annotations": True},
        )
        assert failed_export.status_code == 500
        assert failed_export.json() == {
            "code": "internal_error",
            "message": "internal server error",
        }
        assert len(failed_export_paths) == 1
        assert not failed_export_paths[0].exists()

        monkeypatch.setattr(
            "quirebase.documents.bundles.export_annotations",
            fake_export_annotations,
        )

        async def failing_record(*args, **kwargs):
            await asyncio.sleep(0)
            raise RuntimeError("audit recording failed")

        monkeypatch.setattr(
            "quirebase.documents.bundles._record_revision_pdf_export",
            failing_record,
        )
        exported_paths.clear()
        user = await db.get(User, item.created_by)
        with pytest.raises(RuntimeError, match="audit recording failed"):
            await export_revision_pdf(
                db,
                user,
                item.id,
                revision.id,
                include_annotations=True,
            )
        assert len(exported_paths) == 1
        assert not exported_paths[0].exists()

        underlined = await client.post(
            f"/api/v1/items/{item.id}/annotations",
            headers={"X-CSRF-Token": "test-csrf"},
            json={
                "id": str(uuid4()),
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "underline",
                "scope": "private",
                "selected_text": "underlined text",
                "body": "underline comment",
                "payload": {
                    "type": "underline",
                    "rect": {"x": 10, "y": 10, "width": 20, "height": 10},
                    "style": {"stroke_color": "#FF5959", "opacity": 0.9},
                    "segment_rects": [{"x": 10, "y": 10, "width": 20, "height": 10}],
                },
            },
        )
        assert underlined.status_code == 201
        assert underlined.json()["kind"] == "underline"
        assert underlined.json()["payload"]["style"]["stroke_color"] == "#FF5959"

        conflict = await client.patch(
            f"/api/v1/items/{item.id}/annotations/{annotation['id']}",
            headers={"X-CSRF-Token": "test-csrf"},
            json={
                "version": 99,
                "page_index": annotation["page_index"],
                "kind": annotation["kind"],
                "scope": annotation["scope"],
                "project_id": annotation["project_id"],
                "body": annotation["body"],
                "selected_text": annotation["selected_text"],
                "payload": annotation["payload"],
            },
        )
        assert conflict.status_code == 409

        deleted = await client.delete(
            f"/api/v1/items/{item.id}/annotations/{annotation['id']}",
            headers={"X-CSRF-Token": "test-csrf"},
            params={"version": annotation["version"]},
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True}
        stale_restore = await client.post(
            f"/api/v1/items/{item.id}/annotations/{annotation['id']}/restore",
            headers={"X-CSRF-Token": "test-csrf"},
            params={"version": annotation["version"]},
        )
        assert stale_restore.status_code == 409
        restored = await client.post(
            f"/api/v1/items/{item.id}/annotations/{annotation['id']}/restore",
            headers={"X-CSRF-Token": "test-csrf"},
            params={"version": annotation["version"] + 1},
        )
        assert restored.status_code == 200
        assert restored.json()["version"] == annotation["version"] + 2
        assert restored.json()["replies"] == []
        assert await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "annotation.delete",
                AuditEvent.target_id == annotation["id"],
            )
        )
        assert await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "annotation.restore",
                AuditEvent.target_id == annotation["id"],
            )
        )
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_project_viewer_can_create_annotations(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    owner_client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    viewer = User(username="annotation-viewer", password_hash="unused")
    project = Project(name="Readable annotations", created_by=item.created_by)
    db.add_all([viewer, project])
    await db.flush()
    db.add_all([
        ProjectItem(project_id=project.id, item_id=item.id),
        ProjectMember(project_id=project.id, user_id=viewer.id, role="viewer"),
        LoginSession(
            token_hash=token_hash("annotation-viewer-session"),
            user_id=viewer.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    ])
    await db.commit()

    try:
        owner_client.cookies.set(
            get_settings().session_cookie,
            "annotation-viewer-session",
        )
        viewer = await owner_client.get(f"/api/v1/items/{item.id}/revisions/{revision.id}/viewer")
        created = await owner_client.post(
            f"/api/v1/items/{item.id}/annotations",
            json={
                "id": str(uuid4()),
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "note",
                "scope": "private",
                "body": "Reader note",
                "payload": {
                    "type": "note",
                    "rect": {"x": 10, "y": 10, "width": 20, "height": 20},
                },
            },
        )

        assert viewer.status_code == 200
        assert viewer.json()["editable"] is True
        assert created.status_code == 201
    finally:
        await owner_client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_overview_uses_the_ready_revision_thumbnail(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    thumbnail = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"\x89PNG\r\n\x1a\nthumbnail", max_bytes=100
    )
    revision.thumbnail_object_key = thumbnail.key
    await async_db.commit()
    thumbnail_url = f"/api/v1/items/{item.id}/thumbnail"

    try:
        response = await client.get(thumbnail_url)

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == b"\x89PNG\r\n\x1a\nthumbnail"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_thumbnail_revalidates_all_if_none_match_forms(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    thumbnail = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"cached-thumbnail", max_bytes=100
    )
    revision.thumbnail_object_key = thumbnail.key
    await async_db.commit()
    thumbnail_url = f"/api/v1/items/{item.id}/thumbnail"

    try:
        initial = await client.get(thumbnail_url)
        etag = initial.headers["etag"]

        for validator in (
            "*",
            f'"other", {etag}',
            f"W/{etag}",
            f'"opaque,tag", W/{etag}',
        ):
            response = await client.get(thumbnail_url, headers={"If-None-Match": validator})
            assert response.status_code == 304
            assert response.headers["etag"] == etag
            assert response.headers["cache-control"] == "private, no-cache"
            assert response.content == b""

        mismatch = await client.get(
            thumbnail_url,
            headers={"If-None-Match": '"first", W/"second"'},
        )
        assert mismatch.status_code == 200
        assert mismatch.content == b"cached-thumbnail"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_thumbnail_fetches_the_source_checked_for_cache_metadata(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    from quirebase.web.api import documents as documents_api

    client, item, revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    original = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"original-thumbnail", max_bytes=100
    )
    replacement = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"newer-thumbnail-with-a-different-size", max_bytes=100
    )
    revision.thumbnail_object_key = original.key
    await async_db.commit()
    checked_metadata: ObjectMetadata | None = None
    original_head = documents_api.head_item_thumbnail

    async def switch_source_after_head(source):
        nonlocal checked_metadata
        checked_metadata = await original_head(source)
        revision.thumbnail_object_key = replacement.key
        await async_db.flush()
        return checked_metadata

    monkeypatch.setattr(documents_api, "head_item_thumbnail", switch_source_after_head)

    try:
        response = await client.get(f"/api/v1/items/{item.id}/thumbnail")

        assert checked_metadata is not None
        assert response.status_code == 200
        assert response.content == b"original-thumbnail"
        assert response.headers["content-length"] == str(checked_metadata.size)
        assert response.headers["etag"] == checked_metadata.etag
        assert response.headers["cache-control"] == "private, no-cache"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_overview_omits_a_missing_thumbnail(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    thumbnail_url = f"/api/v1/items/{item.id}/thumbnail"

    try:
        response = await client.get(thumbnail_url)
        assert response.status_code == 404
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_deleting_latest_pdf_revision_removes_its_files_and_falls_back_thumbnail(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, old_revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    item_id = item.id
    old_thumbnail = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"old-thumbnail", max_bytes=100
    )
    old_revision.thumbnail_object_key = old_thumbnail.key
    old_revision.full_text = "fallbacksearchtoken"
    key, size = await put_pdf_object(b"%PDF-1.4\nnewer", 100)
    new_revision = FileRevision(
        item_id=item_id,
        object_key=key,
        size=size,
        original_name="newer.pdf",
        page_count=1,
        page_geometry="[[0,0,300,400]]",
        processing_state="ready",
        full_text="deletedsearchtoken",
        created_by=item.created_by,
        created_at=old_revision.created_at + timedelta(seconds=1),
    )
    new_thumbnail = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"new-thumbnail", max_bytes=100
    )
    new_revision.thumbnail_object_key = new_thumbnail.key
    db.add(new_revision)
    await db.commit()
    new_revision_id = new_revision.id
    new_object = local_object_path(key)
    thumbnail_url = f"/api/v1/items/{item_id}/thumbnail"
    index = search_index(db)
    await index.index_revision(db, new_revision.id)
    recommendation = await request_item_tag_recommendation(db, item_id, owner_id=item.created_by)
    previous_generation = recommendation.generation_token
    await db.commit()

    try:
        assert (await client.get(thumbnail_url)).content == b"new-thumbnail"
        assert await index.search(db, "deletedsearchtoken") == [item_id]

        deleted = await client.delete(f"/api/v1/items/{item_id}/revisions/{new_revision_id}")

        assert deleted.status_code == 200
        assert await db.get(FileRevision, new_revision_id) is None
        await document_workflows.delete_unreferenced_objects_step([key, new_thumbnail.key])
        assert not new_object.exists()
        assert not local_object_path(new_thumbnail.key).exists()
        assert (await client.get(thumbnail_url)).content == b"old-thumbnail"
        assert await index.search(db, "deletedsearchtoken") == []
        refreshed = await db.scalar(
            select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_id)
        )
        assert refreshed is not None
        assert refreshed.generation_token == previous_generation
        assert refreshed.generated_at is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_graphical_abstract_attachment_overrides_the_pdf_thumbnail(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    item_id = item.id
    pdf_thumbnail = get_settings().object_dir / "thumbnails" / f"{revision.id}.png"
    pdf_thumbnail.parent.mkdir(parents=True, exist_ok=True)
    pdf_thumbnail.write_bytes(b"pdf-thumbnail")

    try:
        uploaded = await client.post(
            f"/api/v1/items/{item_id}/attachments",
            data={"graphical_abstract": "true"},
            files={"attachment": ("abstract.png", b"\x89PNG\r\n\x1a\ngraphical", "image/png")},
            follow_redirects=False,
        )
        assert uploaded.status_code == 202
        assert uploaded.json()["id"].startswith("upload-attachment:")
        assert await db.scalar(select(Attachment).where(Attachment.item_id == item_id)) is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_graphical_abstract_rejects_content_that_is_not_an_image(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    item_id = item.id

    try:
        uploaded = await client.post(
            f"/api/v1/items/{item_id}/attachments",
            data={"graphical_abstract": "true"},
            files={"attachment": ("abstract.png", b"not really a png", "image/png")},
            follow_redirects=False,
        )

        assert uploaded.status_code == 202
        assert (
            await db.scalar(
                select(func.count()).select_from(Attachment).where(Attachment.item_id == item_id)
            )
            == 0
        )
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_graphical_abstract_rejects_empty_content_without_leaking_staged_object(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    item_id = item.id
    objects_before = set(get_settings().object_dir.rglob("*.bin"))

    try:
        uploaded = await client.post(
            f"/api/v1/items/{item_id}/attachments",
            data={"graphical_abstract": "true"},
            files={"attachment": ("abstract.png", b"", "image/png")},
            follow_redirects=False,
        )

        assert uploaded.status_code == 202
        assert (
            await db.scalar(
                select(func.count()).select_from(Attachment).where(Attachment.item_id == item_id)
            )
            == 0
        )
        assert set(get_settings().object_dir.rglob("*.bin")) != objects_before
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
@pytest.mark.skip(reason="covered by durable upload crash/recovery integration tests")
async def test_cancelled_graphical_abstract_header_read_reclaims_staged_object(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, item.created_by)
    assert owner is not None
    read_started = asyncio.Event()
    stream_released = asyncio.Event()
    staged_released = asyncio.Event()
    object_deleted = asyncio.Event()

    class FakeStagedObject:
        key = "graphical/cancelled.bin"
        size = 12

        async def release(self):
            staged_released.set()

    async def blocking_body():
        try:
            read_started.set()
            await asyncio.Event().wait()
            yield b""
        finally:
            stream_released.set()

    class BlockingStore:
        async def put_cas(self, source, **options):
            return FakeStagedObject()

        async def get_range(self, key, start, end):
            return ObjectResponse(
                metadata=ObjectMetadata(key, 12, None, datetime.now(UTC)),
                byte_range=(start, end),
                body=blocking_body(),
            )

        async def delete(self, key):
            object_deleted.set()
            return True

    monkeypatch.setattr("quirebase.documents.revisions.get_object_store", BlockingStore)
    creating = asyncio.create_task(
        create_attachment(
            db,
            owner,
            item.id,
            b"ignored",
            "abstract.png",
            "image/png",
            role=AttachmentRole.graphical_abstract,
        )
    )
    await read_started.wait()
    creating.cancel()
    with pytest.raises(asyncio.CancelledError):
        await creating

    assert stream_released.is_set()
    assert staged_released.is_set()
    assert object_deleted.is_set()
    assert await db.scalar(select(func.count()).select_from(Attachment)) == 0
    await client.aclose()


@pytest.mark.anyio
async def test_regular_attachment_accepts_non_image_content(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    item_id = item.id

    try:
        uploaded = await client.post(
            f"/api/v1/items/{item_id}/attachments",
            files={"attachment": ("dataset.csv", b"column\nvalue\n", "text/csv")},
            follow_redirects=False,
        )
        assert uploaded.status_code == 202
        assert uploaded.json()["id"].startswith("upload-attachment:")
        assert await db.scalar(select(Attachment).where(Attachment.item_id == item_id)) is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_edit_detects_conflicts_and_updates_search(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        updated = await client.put(
            f"/api/v1/items/{item.id}",
            json={
                "expected_version": 1,
                "metadata": {"title": "Revised Paper", "abstract": "Quantum transport"},
            },
        )
        assert updated.status_code == 200
        await db.refresh(item)
        assert item.version == 2
        assert item.title == "Revised Paper"

        results = await client.get("/api/v1/items", params={"query": "quantum"})
        assert results.status_code == 200
        assert results.json()["items"][0]["title_html"] == "Revised Paper"

        stale = await client.put(
            f"/api/v1/items/{item.id}",
            json={"expected_version": 1, "metadata": {"title": "Lost update"}},
        )
        assert stale.status_code == 409
        await db.refresh(item)
        assert item.title == "Revised Paper"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_edit_uses_atomic_optimistic_lock(async_db, async_session_factory):
    db = async_db
    owner = User(username="concurrent_owner", password_hash="unused")
    db.add(owner)
    await db.flush()
    item = Item(title="Original", created_by=owner.id)
    db.add(item)
    await db.commit()
    owner_id = owner.id
    item_id = item.id

    async with (
        async_session_factory() as first,
        async_session_factory() as second,
    ):
        first_owner = await first.get(User, owner_id)
        second_owner = await second.get(User, owner_id)
        first_item = await first.get(Item, item_id)
        second_item = await second.get(Item, item_id)
        assert first_owner and second_owner and first_item and second_item
        assert first_item.version == second_item.version == 1

        await revise_item_metadata(
            first,
            first_owner,
            item_id,
            first_item.version,
            ItemMetadata(title="First update"),
        )
        with pytest.raises(VersionConflict):
            await revise_item_metadata(
                second,
                second_owner,
                item_id,
                second_item.version,
                ItemMetadata(title="Lost update"),
            )
    db.expire_all()
    refreshed = await db.get(Item, item_id)
    assert refreshed is not None
    assert refreshed.title == "First update"


@pytest.mark.anyio
async def test_content_media_types_at_runtime(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    item_id = item.id
    store = get_object_store()

    try:
        # 1. Attachment downloads retain their stored media type.
        att_key = "attachments/test.pdf"
        await store.put(att_key, b"%PDF-1.4 test")
        attachment = Attachment(
            id=str(uuid4()),
            item_id=item_id,
            object_key=att_key,
            original_name="test.pdf",
            mime_type="application/pdf",
            size=13,
            role=None,
            created_by=item.created_by,
        )
        db.add(attachment)
        await db.flush()

        att_resp = await client.get(f"/api/v1/items/{item_id}/attachments/{attachment.id}/content")
        assert att_resp.status_code == 200
        assert att_resp.headers["content-type"] == "application/pdf"
        assert 'filename="test.pdf"' in att_resp.headers["content-disposition"]

        # 2. Citation text returns text/plain or text/html based on output param
        cite_text = await client.get(f"/api/v1/items/{item_id}/citation/content?output=text")
        assert cite_text.status_code == 200
        assert "text/plain" in cite_text.headers["content-type"]

        cite_html = await client.get(f"/api/v1/items/{item_id}/citation/content?output=html")
        assert cite_html.status_code == 200
        assert "text/html" in cite_html.headers["content-type"]

        # 3. Bibliography returns application/x-bibtex or application/x-research-info-systems
        bib_resp = await client.get(f"/api/v1/items/{item_id}/bibliography?file_format=bibtex")
        assert bib_resp.status_code == 200
        assert "application/x-bibtex" in bib_resp.headers["content-type"]

        ris_resp = await client.get(f"/api/v1/items/{item_id}/bibliography?file_format=ris")
        assert ris_resp.status_code == 200
        assert "application/x-research-info-systems" in ris_resp.headers["content-type"]

        # 4. Graphical abstract thumbnail returns its image media type (e.g. image/jpeg)
        ga_key = "attachments/ga.jpg"
        await store.put(ga_key, b"\xff\xd8\xff test")
        ga_attachment = Attachment(
            id=str(uuid4()),
            item_id=item_id,
            object_key=ga_key,
            original_name="abstract.jpg",
            mime_type="image/jpeg",
            size=11,
            role=AttachmentRole.graphical_abstract,
            created_by=item.created_by,
        )
        db.add(ga_attachment)
        await db.flush()

        thumb_resp = await client.get(f"/api/v1/items/{item_id}/thumbnail")
        assert thumb_resp.status_code == 200
        assert thumb_resp.headers["content-type"] == "image/jpeg"
    finally:
        await client.aclose()
        get_settings.cache_clear()
