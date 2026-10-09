from __future__ import annotations

import asyncio
import json
import zipfile
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pymupdf
import pytest
from advanced_alchemy.types import FileObject
from app_helpers import json_payload
from import_helpers import pdf_import_batch_data
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from storage_helpers import collect_body, local_object_path, put_pdf_object
from test_http import authenticated_async_client
from workspace_helpers import (
    fixture_membership_id,
    fixture_workspace_id,
    provision_initial_workspace,
)

from quirebase.core.crypto import hash_password
from quirebase.core.errors import PermissionDenied, ProjectLifecycleError
from quirebase.core.storage import ObjectMetadata, ObjectResponse
from quirebase.documents import create_item_document_bundle
from quirebase.library import apply_bulk_item_action, bulk_items, download_selected_item_documents
from quirebase.models import (
    AuditEvent,
    FileRevision,
    ImportBatch,
    Item,
    ItemTag,
    PdfAnnotation,
    Project,
    ProjectItem,
    ProjectParticipant,
    ProjectParticipation,
    ProjectState,
    User,
    WorkspaceMember,
    WorkspaceRole,
)
from quirebase.projects import set_project_state
from quirebase.workspaces import archive_workspace


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
            assert key == revision.file.path
            return ObjectResponse(
                metadata=ObjectMetadata(key, revision.file.size, None, datetime.now(UTC)),
                byte_range=(0, revision.file.size),
                body=blocking_body(),
            )

    monkeypatch.setattr("quirebase.documents.bundles.get_object_store", BlockingStore)
    bundle = await create_item_document_bundle(db, owner, item.workspace_id, item.id)

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

    # Creator of the target Project, but viewer of the source Project where the Item resides
    viewer_user = User(
        username="viewer_user",
        password_hash=hash_password("password1234"),
        role="member",
    )
    db.add(viewer_user)
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=item.workspace_id,
            user_id=viewer_user.id,
            role=WorkspaceRole.viewer,
        )
    )

    # Source project where item is shared and viewer is a viewer
    source_project = Project(
        workspace_id=item.workspace_id,
        name="Source Project",
        created_by=item.created_by,
        participation=ProjectParticipation.managed,
    )
    db.add(source_project)
    await db.flush()
    db.add(
        ProjectItem(workspace_id=item.workspace_id, project_id=source_project.id, item_id=item.id)
    )
    db.add(
        ProjectParticipant(
            workspace_id=item.workspace_id,
            project_id=source_project.id,
            user_id=viewer_user.id,
            workspace_member_id=await fixture_membership_id(db, item.workspace_id, viewer_user.id),
        )
    )

    # Target Project created by the viewer
    target_project = Project(
        workspace_id=item.workspace_id,
        name="Target Project",
        created_by=viewer_user.id,
        participation=ProjectParticipation.managed,
    )
    db.add(target_project)
    await db.flush()
    db.add(
        ProjectParticipant(
            workspace_id=item.workspace_id,
            project_id=target_project.id,
            user_id=viewer_user.id,
            workspace_member_id=await fixture_membership_id(db, item.workspace_id, viewer_user.id),
        )
    )
    await db.commit()

    # Attempt to bulk-assign item to target project as viewer_user
    with pytest.raises(PermissionDenied):
        await apply_bulk_item_action(
            db,
            viewer_user,
            item.workspace_id,
            item_ids=[item.id],
            action="add_project",
            project_id=target_project.id,
        )

    # Verify no unauthorized ProjectItem was created
    assignment = await db.scalar(
        select(ProjectItem).where(
            ProjectItem.workspace_id == item.workspace_id,
            ProjectItem.project_id == target_project.id,
            ProjectItem.item_id == item.id,
        )
    )
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

    target_project = Project(
        workspace_id=item.workspace_id,
        name="My Project",
        created_by=owner.id,
        participation=ProjectParticipation.managed,
    )
    db.add(target_project)
    await db.flush()
    db.add(
        ProjectParticipant(
            workspace_id=item.workspace_id,
            project_id=target_project.id,
            user_id=owner.id,
            workspace_member_id=await fixture_membership_id(db, item.workspace_id, owner.id),
        )
    )
    await db.commit()

    await apply_bulk_item_action(
        db,
        owner,
        item.workspace_id,
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
    assert event.detail["item_ids"] == json_payload([item.id])
    await client.aclose()


@pytest.mark.anyio
async def test_bulk_tag_integrity_race_returns_http_conflict(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )

    monkeypatch.setattr(
        bulk_items,
        "_assign_item_tags",
        AsyncMock(
            side_effect=IntegrityError(
                "INSERT INTO item_tags", {}, Exception("tag foreign key disappeared")
            )
        ),
    )
    try:
        response = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/items/bulk",
            json=json_payload({
                "item_ids": [item.id],
                "action": "add_tag",
                "tag_name": "Concurrent Tag",
            }),
        )
        assert response.status_code == 409
        assert response.json()["code"] == "tag_conflict"
        assert await async_db.scalar(select(ItemTag)) is None
        assert (
            await async_db.scalar(
                select(AuditEvent).where(AuditEvent.action == "library.bulk.add_tag")
            )
            is None
        )
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_bulk_action_rejects_archived_project_assignment(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, item.created_by)
    assert owner is not None
    target_project = Project(
        workspace_id=item.workspace_id,
        name="Archived Project",
        created_by=owner.id,
        state=ProjectState.archived,
        participation=ProjectParticipation.managed,
    )
    db.add(target_project)
    await db.flush()
    db.add(
        ProjectParticipant(
            workspace_id=item.workspace_id,
            project_id=target_project.id,
            user_id=owner.id,
            workspace_member_id=await fixture_membership_id(db, item.workspace_id, owner.id),
        )
    )
    await db.commit()

    with pytest.raises(ProjectLifecycleError, match="read-only"):
        await apply_bulk_item_action(
            db,
            owner,
            item.workspace_id,
            item_ids=[item.id],
            action="add_project",
            project_id=target_project.id,
        )

    assert (
        await db.scalar(
            select(ProjectItem).where(
                ProjectItem.workspace_id == item.workspace_id,
                ProjectItem.project_id == target_project.id,
                ProjectItem.item_id == item.id,
            )
        )
        is None
    )
    path = f"/api/v1/workspaces/{item.workspace_id}/projects/{target_project.id}/items/{item.id}"
    response = await client.put(path)
    assert response.status_code == 409
    assert response.json()["code"] == "project_lifecycle_error"

    await archive_workspace(db, owner, item.workspace_id)
    response = await client.put(path)
    assert response.status_code == 409
    assert response.json()["code"] == "workspace_lifecycle_error"
    await client.aclose()


@pytest.mark.anyio
async def test_bulk_action_revalidates_stale_project_state(async_db, async_session_factory):
    owner = User(username="bulk-project-race-owner", password_hash="unused")
    async_db.add(owner)
    await async_db.flush()

    await provision_initial_workspace(async_db, owner)
    item = Item(
        workspace_id=fixture_workspace_id(owner), title="Bulk project race", created_by=owner.id
    )
    project = Project(
        workspace_id=fixture_workspace_id(owner),
        name="Bulk project race",
        created_by=owner.id,
        participation=ProjectParticipation.managed,
    )
    async_db.add_all([item, project])
    await async_db.flush()
    async_db.add(
        ProjectParticipant(
            workspace_id=fixture_workspace_id(owner),
            project_id=project.id,
            user_id=owner.id,
            workspace_member_id=await fixture_membership_id(
                async_db, fixture_workspace_id(owner), owner.id
            ),
        )
    )
    await async_db.commit()

    async with async_session_factory() as bulk_session:
        bulk_owner = await bulk_session.get(User, owner.id)
        assert bulk_owner is not None
        stale_project = await bulk_session.get(Project, project.id)
        stale_member = await bulk_session.scalar(
            select(ProjectParticipant).where(
                ProjectParticipant.workspace_id == fixture_workspace_id(owner),
                ProjectParticipant.project_id == project.id,
                ProjectParticipant.user_id == owner.id,
            )
        )
        assert stale_project is not None and stale_member is not None

        async with async_session_factory() as lifecycle_session:
            lifecycle_owner = await lifecycle_session.get(User, owner.id)
            assert lifecycle_owner is not None
            await set_project_state(
                lifecycle_session,
                lifecycle_owner,
                fixture_workspace_id(owner),
                project.id,
                ProjectState.archived,
            )

        with pytest.raises(ProjectLifecycleError, match="Project is read-only"):
            await apply_bulk_item_action(
                bulk_session,
                bulk_owner,
                fixture_workspace_id(owner),
                item_ids=[item.id],
                action="add_project",
                project_id=project.id,
            )

    assert (
        await async_db.scalar(
            select(ProjectItem).where(
                ProjectItem.workspace_id == fixture_workspace_id(owner),
                ProjectItem.project_id == project.id,
                ProjectItem.item_id == item.id,
            )
        )
        is None
    )


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
    object_path = local_object_path(revision.file.path)
    db.add(
        ImportBatch(
            workspace_id=item.workspace_id,
            actor_id=owner.id,
            file_format="pdf",
            **pdf_import_batch_data([{"_pdf": {"object_key": revision.file.path}}]),
            errors=[],
        )
    )
    await db.commit()

    await apply_bulk_item_action(
        db,
        owner,
        item.workspace_id,
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

    archive = await download_selected_item_documents(db, owner, item.workspace_id, [item.id])
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
    detail = event.detail
    assert detail["item_ids"] == json_payload([item.id])
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
            workspace_id=item.workspace_id,
            item_id=item.id,
            processing_state="ready",
            created_by=owner.id,
            file=FileObject(
                backend="documents",
                filename=key,
                size=size,
                content_type="application/pdf",
                metadata={"original_name": "published.pdf"},
            ),
        )
    )
    await db.commit()

    archive = await create_item_document_bundle(db, owner, item.workspace_id, item.id)
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
    revision.file = FileObject(**(revision.file.to_dict() | {"filename": key, "size": size}))
    annotation = PdfAnnotation(
        workspace_id=item.workspace_id,
        file_revision_id=revision.id,
        item_id=item.id,
        page_index=0,
        author_id=owner.id,
        kind="highlight",
        scope="private",
        selected_text="Result",
        payload={
            "type": "highlight",
            "rect": {"x": 20, "y": 280, "width": 80, "height": 20},
            "style": {
                "stroke_color": "#FFEB33",
                "fill_color": None,
                "text_color": None,
                "opacity": 0.35,
                "stroke_width": 1,
                "dash_pattern": [],
            },
            "segment_rects": [{"x": 20, "y": 280, "width": 80, "height": 20}],
        },
    )
    db.add(annotation)
    await db.commit()

    archive = await create_item_document_bundle(
        db, owner, item.workspace_id, item.id, include_annotations=True
    )

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
        db, owner, item.workspace_id, [item.id], include_annotations=True
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
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    other_user = User(username="private_owner", password_hash="test-hash", role="member")
    db.add(other_user)
    await db.flush()

    await provision_initial_workspace(db, other_user)
    private_item = Item(
        workspace_id=fixture_workspace_id(other_user),
        title="Private metadata",
        created_by=other_user.id,
    )
    db.add(private_item)
    await db.commit()

    response = await client.post(
        f"/api/v1/workspaces/{item.workspace_id}/items/bibliography",
        json=json_payload({"file_format": "bibtex", "item_ids": [private_item.id]}),
    )

    assert response.status_code == 422
    assert "Private metadata" not in response.text
    await client.aclose()


@pytest.mark.anyio
async def test_bulk_archive_roots_are_unique_for_uuid7_and_adversarial_titles(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    from quirebase.documents.bundles import assemble_document_bundle

    db = async_db
    client, original, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, original.created_by)
    ids = [UUID(f"01930abc-0000-7000-8000-{i:012d}") for i in range(1, 6)]
    items = [
        Item(
            id=item_id,
            workspace_id=original.workspace_id,
            created_by=owner.id,
            title="Same title",
            bibtex_id=(f"Same-{ids[2]}" if i == 0 else "Same"),
        )
        for i, item_id in enumerate(ids)
    ]
    db.add_all(items)
    await db.flush()
    revisions = [
        FileRevision(
            workspace_id=original.workspace_id,
            item_id=item.id,
            created_by=owner.id,
            processing_state="ready",
            file=revision.file,
        )
        for item in items
    ]
    db.add_all(revisions)
    await db.commit()
    archive = await assemble_document_bundle(db, owner, items)
    with zipfile.ZipFile(await collect_body(archive.body)) as bundle:
        names = bundle.namelist()
        assert len(names) == len(set(names))
        manifest = json.loads(bundle.read("manifest.json"))
        folders = [entry["folder"] for entry in manifest["items"]]
        assert len(set(folders)) == len(items)
        assert len([name for name in names if name.endswith(".pdf")]) == len(items)
        for item, revision, entry in zip(items, revisions, manifest["items"], strict=True):
            assert entry["item_id"] == str(item.id)
            pdfs = json.loads(bundle.read(f"{entry['folder']}/manifest.json"))["pdf_revisions"]
            assert len(pdfs) == 1 and pdfs[0]["revision_id"] == str(revision.id)
            assert pdfs[0]["filename"].startswith(entry["folder"] + "/")
            assert pdfs[0]["filename"] in names
    await client.aclose()
