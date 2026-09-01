from __future__ import annotations

import asyncio
import json
import zipfile
from datetime import UTC, datetime

import pymupdf
import pytest
from sqlalchemy import select
from storage_helpers import collect_body, local_object_path, put_pdf_object
from test_http import authenticated_async_client

from quirebase.core.crypto import hash_password
from quirebase.core.errors import PermissionDenied
from quirebase.core.storage import ObjectMetadata, ObjectResponse
from quirebase.documents import create_item_document_bundle
from quirebase.library import apply_bulk_item_action, download_selected_item_documents
from quirebase.models import (
    AuditEvent,
    FileRevision,
    ImportBatch,
    Item,
    PdfAnnotation,
    PdfAnnotationSegment,
    Project,
    ProjectItem,
    ProjectMember,
    User,
)


@pytest.mark.anyio
async def test_streaming_bundle_cancellation_releases_object_stream(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, item.created_by)
    assert owner is not None
    started = asyncio.Event()
    released = asyncio.Event()

    async def blocking_body():
        try:
            started.set()
            yield b"first chunk"
            await asyncio.Event().wait()
        finally:
            released.set()

    class BlockingStore:
        async def get(self, key):
            assert key == revision.object_key
            return ObjectResponse(
                metadata=ObjectMetadata(key, revision.size, None, datetime.now(UTC)),
                byte_range=(0, revision.size),
                body=blocking_body(),
            )

    monkeypatch.setattr("quirebase.documents.bundles.get_object_store", BlockingStore)
    bundle = await create_item_document_bundle(db, owner, item.id)

    async def consume():
        async for _chunk in bundle.body:
            pass

    task = asyncio.create_task(consume())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released.is_set()
    await client.aclose()


@pytest.mark.anyio
async def test_bulk_action_blocks_unauthorized_assignment_to_project(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )

    # Owner of target project, but viewer of source project where item resides
    viewer_user = User(
        username="viewer_user",
        password_hash=hash_password("password1234"),
        role="member",
    )
    db.add(viewer_user)
    await db.flush()

    # Source project where item is shared and viewer is a viewer
    source_project = Project(name="Source Project", created_by=item.created_by)
    db.add(source_project)
    await db.flush()
    db.add(ProjectItem(project_id=source_project.id, item_id=item.id))
    db.add(ProjectMember(project_id=source_project.id, user_id=viewer_user.id, role="viewer"))

    # Target project owned by viewer
    target_project = Project(name="Target Project", created_by=viewer_user.id)
    db.add(target_project)
    await db.flush()
    db.add(ProjectMember(project_id=target_project.id, user_id=viewer_user.id, role="owner"))
    await db.commit()

    # Attempt to bulk-assign item to target project as viewer_user
    with pytest.raises(PermissionDenied, match="all selected items must be editable"):
        await apply_bulk_item_action(
            db,
            viewer_user,
            item_ids=[item.id],
            action="add_project",
            project_id=target_project.id,
        )

    # Verify no unauthorized ProjectItem was created
    assignment = await db.get(ProjectItem, (target_project.id, item.id))
    assert assignment is None
    await client.aclose()


@pytest.mark.anyio
async def test_bulk_action_records_single_bulk_audit_event(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, item.created_by)
    assert owner is not None

    target_project = Project(name="My Project", created_by=owner.id)
    db.add(target_project)
    await db.flush()
    db.add(ProjectMember(project_id=target_project.id, user_id=owner.id, role="owner"))
    await db.commit()

    await apply_bulk_item_action(
        db,
        owner,
        item_ids=[item.id],
        action="add_project",
        project_id=target_project.id,
    )

    event = await db.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "library.bulk.add_project")
        .order_by(AuditEvent.created_at.desc())
    )
    assert event is not None
    assert json.loads(event.detail)["item_ids"] == [item.id]
    await client.aclose()


@pytest.mark.anyio
async def test_bulk_delete_preserves_object_referenced_by_pending_pdf_import(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, item.created_by)
    assert owner is not None
    object_path = local_object_path(revision.object_key)
    db.add(
        ImportBatch(
            owner_id=owner.id,
            file_format="pdf",
            records=json.dumps([{"_pdf": {"object_key": revision.object_key}}]),
            errors="[]",
        )
    )
    await db.commit()

    await apply_bulk_item_action(
        db,
        owner,
        item_ids=[item.id],
        action="delete_items",
        confirm_delete="delete",
    )

    assert object_path.is_file()
    await client.aclose()


@pytest.mark.anyio
async def test_bulk_download_pdfs_records_audit_event(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, item.created_by)
    assert owner is not None

    archive = await download_selected_item_documents(db, owner, [item.id])
    archive_bytes = await collect_body(archive.body)
    assert archive_bytes.getvalue()
    assert archive.filename == "quirebase-selected-pdfs.zip"
    with zipfile.ZipFile(archive_bytes) as bundle:
        assert "manifest.json" in bundle.namelist()
        assert "Paper/manifest.json" in bundle.namelist()
        assert "Paper/Paper-pdf-v01-paper.pdf" in bundle.namelist()

    event = await db.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "library.bulk.download_pdfs")
        .order_by(AuditEvent.created_at.desc())
    )
    assert event is not None
    detail = json.loads(event.detail)
    assert detail["item_ids"] == [item.id]
    assert detail["include_annotations"] is False
    assert detail["include_supplements"] is False
    await client.aclose()


@pytest.mark.anyio
async def test_item_download_bundle_contains_all_pdf_versions_with_manifest(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, item.created_by)
    assert owner is not None
    key, size = await put_pdf_object(b"%PDF-1.4\nsecond-pdf", 100)
    db.add(
        FileRevision(
            item_id=item.id,
            object_key=key,
            size=size,
            original_name="published.pdf",
            processing_state="ready",
            created_by=owner.id,
        )
    )
    await db.commit()

    archive = await create_item_document_bundle(db, owner, item.id)
    assert archive.filename == "Paper-pdfs.zip"
    with zipfile.ZipFile(await collect_body(archive.body)) as bundle:
        names = bundle.namelist()
        assert "manifest.json" in names
        assert sum(name.endswith("paper.pdf") for name in names) == 1
        assert sum(name.endswith("published.pdf") for name in names) == 1
        manifest = json.loads(bundle.read("manifest.json"))
        assert len(manifest["pdf_revisions"]) == 2
        assert all("-pdf-v" in name for name in names if name.endswith(".pdf"))
    await client.aclose()


@pytest.mark.anyio
async def test_item_download_embeds_annotations_in_pdf_without_a_sidecar(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, item.created_by)
    assert owner is not None
    with pymupdf.open() as document:
        document.new_page(width=300, height=400)
        source = document.tobytes()
    key, size = await put_pdf_object(source, 100_000)
    revision.object_key = key
    revision.size = size
    annotation = PdfAnnotation(
        file_revision_id=revision.id,
        author_id=owner.id,
        kind="highlight",
        scope="private",
        color="yellow",
        selected_text="Result",
    )
    annotation.segments = [
        PdfAnnotationSegment(
            page_index=0,
            ordinal=0,
            x1=20,
            y1=300,
            x2=100,
            y2=300,
            x3=20,
            y3=280,
            x4=100,
            y4=280,
        )
    ]
    db.add(annotation)
    await db.commit()

    archive = await create_item_document_bundle(db, owner, item.id, include_annotations=True)

    assert archive.filename == "Paper-annotated-pdfs.zip"
    with zipfile.ZipFile(await collect_body(archive.body)) as bundle:
        names = bundle.namelist()
        assert not any(name.startswith("annotations-") for name in names)
        pdf_name = next(name for name in names if name.endswith(".pdf"))
        assert "-annotated-pdf-" in pdf_name
        with pymupdf.open(stream=bundle.read(pdf_name), filetype="pdf") as document:
            page = document[0]
            exported = list(page.annots())
            assert [record.type[1] for record in exported] == ["Highlight"]
            assert exported[0].info["title"] == owner.username

    bulk_archive = await download_selected_item_documents(
        db, owner, [item.id], include_annotations=True
    )
    assert bulk_archive.filename == "quirebase-selected-annotated-pdfs.zip"
    with zipfile.ZipFile(await collect_body(bulk_archive.body)) as bundle:
        assert "manifest.json" in bundle.namelist()
        assert "Paper/manifest.json" in bundle.namelist()
        pdf_name = next(
            name
            for name in bundle.namelist()
            if name.startswith("Paper/") and name.endswith(".pdf")
        )
        assert "-annotated-pdf-" in pdf_name
        with pymupdf.open(stream=bundle.read(pdf_name), filetype="pdf") as document:
            page = document[0]
            exported = next(page.annots())
            assert exported.info["title"] == owner.username
    await client.aclose()


@pytest.mark.anyio
async def test_bulk_export_rejects_inaccessible_items(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, _item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    other_user = User(username="private_owner", password_hash="test-hash", role="member")
    db.add(other_user)
    await db.flush()
    private_item = Item(title="Private metadata", created_by=other_user.id)
    db.add(private_item)
    await db.commit()

    response = await client.post(
        "/library/bulk",
        data={"csrf_token": "test-csrf", "action": "export_bibtex", "item_ids": private_item.id},
    )

    assert response.status_code == 422
    assert "Private metadata" not in response.text
    await client.aclose()
