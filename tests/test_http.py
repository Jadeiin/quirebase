import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from html import unescape
from io import BytesIO

import httpx2
import pytest
from sqlalchemy import func, select

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
        csrf_token="test-csrf",
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    item = Item(title="Paper", created_by=user.id)
    db.add_all([login, item])
    await db.flush()
    key, digest, size = LocalObjectStore().put_pdf(source=BytesIO(b"%PDF-1.4\ntest"), maximum=100)
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
    await db.commit()

    test_app = create_app(mcp_session_factory=session_factory)

    async def override_db():
        await asyncio.sleep(0)
        yield db

    test_app.dependency_overrides[get_db] = override_db
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=test_app),
        base_url="http://testserver",
        headers={"Accept-Language": "zh-CN,zh;q=0.9"},
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
        viewer = await client.get(f"/items/{item.id}/pdf/{revision.id}")
        assert viewer.status_code == 200
        assert 'lang="zh-CN"' in viewer.text
        assert "删除所选批注" in viewer.text
        encoded_messages = re.search(r'data-i18n="([^"]+)"', viewer.text)
        assert encoded_messages is not None
        messages = json.loads(unescape(encoded_messages.group(1)))
        assert messages["selectOwnAnnotation"] == "请选择一条你创建的批注。"

        content = await client.get(
            f"/documents/{item.id}/revisions/{revision.id}/content",
            headers={"Range": "bytes=0-4"},
        )
        assert content.status_code == 206
        assert content.content == b"%PDF-"
        assert content.headers["content-range"].startswith("bytes 0-4/")

        created = await client.post(
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
        await db.commit()
        mismatched = await client.get(f"/documents/{other_item.id}/revisions/{revision.id}/export")
        assert mismatched.status_code == 404

        revision.original_name = "论文.pdf"
        await db.commit()
        unicode_content = await client.get(f"/documents/{item.id}/revisions/{revision.id}/content")
        unicode_range = await client.get(
            f"/documents/{item.id}/revisions/{revision.id}/content",
            headers={"Range": "bytes=0-4"},
        )
        unicode_download = await client.get(
            f"/documents/{item.id}/revisions/{revision.id}/export",
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
        with pytest.raises(RuntimeError, match="annotation export failed"):
            await client.get(
                f"/documents/{item.id}/revisions/{revision.id}/export",
                params={"include_annotations": True},
            )
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

        conflict = await client.patch(
            f"/documents/{item.id}/annotations/{annotation['id']}",
            headers={"X-CSRF-Token": "test-csrf"},
            json={"version": 99, "color": "red"},
        )
        assert conflict.status_code == 409

        deleted = await client.delete(
            f"/documents/{item.id}/annotations/{annotation['id']}",
            headers={"X-CSRF-Token": "test-csrf"},
        )
        assert deleted.status_code == 204
        assert deleted.content == b""
        assert await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "annotation.delete",
                AuditEvent.target_id == annotation["id"],
            )
        )
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_overview_uses_the_ready_revision_thumbnail(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    thumbnail = get_settings().object_dir / "thumbnails" / f"{revision.id}.png"
    thumbnail.parent.mkdir(parents=True, exist_ok=True)
    thumbnail.write_bytes(b"\x89PNG\r\n\x1a\nthumbnail")
    thumbnail_url = f"/documents/{item.id}/thumbnail"

    try:
        overview = await client.get(f"/items/{item.id}")
        response = await client.get(thumbnail_url)

        assert f'src="{thumbnail_url}"' in overview.text
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == thumbnail.read_bytes()
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
    thumbnail_url = f"/documents/{item.id}/thumbnail"

    try:
        overview = await client.get(f"/items/{item.id}")

        assert thumbnail_url not in overview.text
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
    await db.commit()
    new_object = store.path(key)
    new_thumbnail = get_settings().object_dir / "thumbnails" / f"{new_revision.id}.png"
    new_thumbnail.write_bytes(b"new-thumbnail")
    thumbnail_url = f"/documents/{item.id}/thumbnail"
    index = search_index(db)
    await index.index_item(db, item.id)
    recommendation = await request_item_tag_recommendation(db, item.id, owner_id=item.created_by)
    previous_fingerprint = recommendation.input_fingerprint
    previous_generation = recommendation.generation_token
    await db.commit()

    try:
        assert (await client.get(thumbnail_url)).content == b"new-thumbnail"
        assert await index.search(db, "deletedsearchtoken") == [item.id]

        deleted = await client.post(
            f"/items/{item.id}/pdf/{new_revision.id}/delete",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )

        assert deleted.status_code == 303
        assert deleted.headers["location"] == f"/items/{item.id}/files"
        assert await db.get(FileRevision, new_revision.id) is None
        assert not new_object.exists()
        assert not new_thumbnail.exists()
        assert (await client.get(thumbnail_url)).content == b"old-thumbnail"
        assert await index.search(db, "deletedsearchtoken") == []
        assert await index.search(db, "fallbacksearchtoken") == [item.id]
        refreshed = await db.scalar(
            select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item.id)
        )
        assert refreshed is not None
        assert refreshed.input_fingerprint != previous_fingerprint
        assert refreshed.generation_token == previous_generation + 1
        assert refreshed.generated_at is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_pdf_revision_cannot_be_deleted_while_inspection_is_running(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
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
    await db.commit()

    try:
        deleted = await client.post(
            f"/items/{item.id}/pdf/{revision.id}/delete",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )

        assert deleted.status_code == 409
        assert await db.get(FileRevision, revision.id) is not None
        assert await db.get(Job, job.id) is not None
        assert object_path.exists()
        assert thumbnail.exists()
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_deleting_pdf_revision_cancels_pending_annotation_exports(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    job = Job(
        kind="pdf.export_annotations",
        payload=json.dumps({"revision_id": revision.id}),
        idempotency_key=f"pdf.export:test:{revision.id}:none:pending",
        owner_id=item.created_by,
        state="pending",
    )
    db.add(job)
    await db.commit()

    try:
        deleted = await client.post(
            f"/items/{item.id}/pdf/{revision.id}/delete",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )

        assert deleted.status_code == 303
        assert await db.get(FileRevision, revision.id) is None
        assert await db.get(Job, job.id) is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_pdf_revision_cannot_be_deleted_while_annotation_export_is_running(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
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
    await db.commit()

    try:
        deleted = await client.post(
            f"/items/{item.id}/pdf/{revision.id}/delete",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )

        assert deleted.status_code == 409
        assert await db.get(FileRevision, revision.id) is not None
        assert await db.get(Job, job.id) is not None
        assert object_path.exists()
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
    pdf_thumbnail = get_settings().object_dir / "thumbnails" / f"{revision.id}.png"
    pdf_thumbnail.parent.mkdir(parents=True, exist_ok=True)
    pdf_thumbnail.write_bytes(b"pdf-thumbnail")

    try:
        uploaded = await client.post(
            f"/items/{item.id}/attachments",
            data={"csrf_token": "test-csrf", "graphical_abstract": "true"},
            files={"attachment": ("abstract.png", b"\x89PNG\r\n\x1a\ngraphical", "image/png")},
            follow_redirects=False,
        )
        attachment = await db.scalar(select(Attachment).where(Attachment.item_id == item.id))

        assert uploaded.status_code == 303
        assert attachment.role == "graphical_abstract"
        assert (await client.get(f"/documents/{item.id}/thumbnail")).content.endswith(b"graphical")
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

    try:
        uploaded = await client.post(
            f"/items/{item.id}/attachments",
            data={"csrf_token": "test-csrf", "graphical_abstract": "true"},
            files={"attachment": ("abstract.png", b"not really a png", "image/png")},
            follow_redirects=False,
        )

        assert uploaded.status_code == 422
        assert (
            await db.scalar(
                select(func.count()).select_from(Attachment).where(Attachment.item_id == item.id)
            )
            == 0
        )
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_regular_attachment_accepts_non_image_content(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )

    try:
        uploaded = await client.post(
            f"/items/{item.id}/attachments",
            data={"csrf_token": "test-csrf"},
            files={"attachment": ("dataset.csv", b"column\nvalue\n", "text/csv")},
            follow_redirects=False,
        )
        attachment = await db.scalar(select(Attachment).where(Attachment.item_id == item.id))
        assert attachment is not None

        assert uploaded.status_code == 303
        assert attachment.mime_type == "text/csv"
        assert attachment.role is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_replacing_and_deleting_graphical_abstract_preserves_attachment_and_falls_back(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    pdf_thumbnail = get_settings().object_dir / "thumbnails" / f"{revision.id}.png"
    pdf_thumbnail.parent.mkdir(parents=True, exist_ok=True)
    pdf_thumbnail.write_bytes(b"pdf-thumbnail")

    try:
        for name, content in (("first.png", b"first-image"), ("second.png", b"second-image")):
            response = await client.post(
                f"/items/{item.id}/attachments",
                data={"csrf_token": "test-csrf", "graphical_abstract": "true"},
                files={"attachment": (name, b"\x89PNG\r\n\x1a\n" + content, "image/png")},
                follow_redirects=False,
            )
            assert response.status_code == 303

        first, second = (
            await db.scalars(
                select(Attachment)
                .where(Attachment.item_id == item.id)
                .order_by(Attachment.created_at)
            )
        ).all()
        second_object = LocalObjectStore().path(second.object_key)
        assert first.role is None
        assert second.role == "graphical_abstract"
        assert (await client.get(f"/documents/{item.id}/thumbnail")).content.endswith(
            b"second-image"
        )

        deleted = await client.post(
            f"/items/{item.id}/attachments/{second.id}/delete",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )

        assert deleted.status_code == 303
        assert await db.get(Attachment, first.id) is not None
        assert await db.get(Attachment, second.id) is None
        assert not second_object.exists()
        assert (await client.get(f"/documents/{item.id}/thumbnail")).content == b"pdf-thumbnail"
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
        updated = await client.post(
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
        await db.refresh(item)
        assert item.version == 2
        assert item.title == "Revised Paper"

        results = await client.get("/?q=quantum")
        assert results.status_code == 200
        assert "Revised Paper" in results.text

        stale = await client.post(
            f"/items/{item.id}/edit",
            data={"csrf_token": "test-csrf", "version": 1, "title": "Lost update"},
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
