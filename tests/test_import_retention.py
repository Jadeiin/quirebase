from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from advanced_alchemy.types import FileObject
from provider_helpers import provider_runtime
from sqlalchemy import select
from workspace_helpers import provision_initial_workspace

from quirebase.core.errors import PermissionDenied
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.documents import delete_unreferenced_objects
from quirebase.library import (
    ImportBatchUnavailable,
    LibraryFilter,
    commit_import_batch,
    delete_import_batch,
    get_import_batch_preview,
    list_import_batches,
    purge_expired_import_batches,
    retry_pdf_import_batch,
    search_library,
    stage_identifiers_import_batch,
    stage_import_batch,
)
from quirebase.library.imports import BatchConflict, finalize_pdf_import_batch
from quirebase.models import (
    FileRevision,
    ImportBatch,
    ImportBatchStatus,
    Item,
    User,
    WorkspaceMember,
    WorkspaceRole,
)

pytestmark = pytest.mark.anyio


async def _preview(db, actor, workspace_id, title):
    return await stage_import_batch(
        db,
        actor,
        workspace_id,
        json.dumps([{"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": title}]).encode(),
        "commonmeta",
    )


async def test_workspace_import_directory_lists_summaries_and_keeps_empty_page_total(
    persistence_db,
):
    db = persistence_db
    owner = User(username=f"directory-{uuid4()}", password_hash="unused")
    db.add(owner)
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    await db.commit()
    ready = await _preview(db, owner, workspace.id, "Ready preview")
    failed = await _preview(db, owner, workspace.id, "Failed preview")
    pending = await _preview(db, owner, workspace.id, "Preparing preview")
    preparing = await db.get(ImportBatch, pending.id)
    preparing.status = ImportBatchStatus.pending
    row = await db.get(ImportBatch, failed.id)
    row.status = ImportBatchStatus.failed
    row.errors = [{"message": "inspection failed"}]
    await db.commit()
    rows, total = await list_import_batches(db, owner, workspace.id, limit=1)
    assert total == 3 and len(rows) == 1 and rows[0].id == pending.id
    assert rows[0].record_count == 1 and rows[0].diagnostic_count == 0
    assert not hasattr(rows[0], "records") and not hasattr(rows[0], "workflow_id")
    assert await list_import_batches(db, owner, workspace.id, offset=20) == ([], 3)
    uncommitted, total = await list_import_batches(db, owner, workspace.id, view="uncommitted")
    assert total == 3 and {row.status for row in uncommitted} == {"pending", "ready", "failed"}
    assert next(row for row in uncommitted if row.id == failed.id).diagnostic_count == 1
    await commit_import_batch(db, owner, workspace.id, ready.id)
    uncommitted, total = await list_import_batches(db, owner, workspace.id)
    assert total == 2 and {row.id for row in uncommitted} == {pending.id, failed.id}
    committed, total = await list_import_batches(db, owner, workspace.id, view="committed")
    assert total == 1 and committed[0].id == ready.id and committed[0].record_count == 1


async def test_import_receipt_deletion_preserves_items_and_invalidates_old_filters(persistence_db):
    db = persistence_db
    owner = User(username=f"receipt-owner-{uuid4()}", password_hash="unused")
    editor = User(username=f"receipt-editor-{uuid4()}", password_hash="unused")
    viewer = User(username=f"receipt-viewer-{uuid4()}", password_hash="unused")
    db.add_all([owner, editor, viewer])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    db.add_all([
        WorkspaceMember(workspace_id=workspace.id, user_id=editor.id, role=WorkspaceRole.editor),
        WorkspaceMember(workspace_id=workspace.id, user_id=viewer.id, role=WorkspaceRole.viewer),
    ])
    await db.commit()
    workspace_id = workspace.id
    preview = await _preview(db, owner, workspace.id, "Retained Item")
    item_ids = (await commit_import_batch(db, owner, workspace_id, preview.id)).committed_item_ids
    with pytest.raises(PermissionDenied):
        await delete_import_batch(db, viewer, workspace_id, preview.id)
    await delete_import_batch(db, editor, workspace_id, preview.id)
    assert (
        tuple(await db.scalars(select(Item.id).where(Item.workspace_id == workspace_id)))
        == item_ids
    )
    for operation in (
        get_import_batch_preview,
        commit_import_batch,
        retry_pdf_import_batch,
        delete_import_batch,
    ):
        with pytest.raises(ImportBatchUnavailable):
            await operation(db, editor, workspace_id, preview.id)
    with pytest.raises(ImportBatchUnavailable):
        await search_library(db, editor, workspace_id, LibraryFilter(import_batch=preview.id))


async def test_committing_import_releases_candidate_diagnostics_and_workflow_link(persistence_db):
    db = persistence_db
    owner = User(username=f"release-{uuid4()}", password_hash="unused")
    db.add(owner)
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    await db.commit()
    preview = await _preview(db, owner, workspace.id, "Release inputs")
    row = await db.get(ImportBatch, preview.id)
    row.errors = [{"message": "source warning", "severity": "warning"}]
    row.workflow_id = "old-preparation"
    await db.commit()
    receipt = await commit_import_batch(db, owner, workspace.id, preview.id)
    assert receipt.id == preview.id and receipt.file_format == preview.file_format
    assert receipt.created_at == preview.created_at and receipt.status == "committed"
    assert receipt.records == () and receipt.errors == () and receipt.workflow_id is None
    assert len(receipt.committed_item_ids) == 1
    assert await get_import_batch_preview(db, owner, workspace.id, preview.id) == receipt
    assert await commit_import_batch(db, owner, workspace.id, preview.id) == receipt


async def _owner(db):
    owner = User(username=f"cleanup-{uuid4()}", password_hash="unused")
    db.add(owner)
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    await db.commit()
    return owner, workspace


async def test_bibliography_without_valid_candidates_is_failed(persistence_db):
    db = persistence_db
    owner, workspace = await _owner(db)
    preview = await stage_import_batch(
        db,
        owner,
        workspace.id,
        b'[{"id":"urn:uuid:00000000-0000-4000-8000-000000000001","type":"UnknownType"}]',
        "commonmeta",
    )
    assert preview.status == "failed" and preview.records == () and preview.errors
    assert (await get_import_batch_preview(db, owner, workspace.id, preview.id)).status == "failed"
    with pytest.raises(BatchConflict, match="not ready"):
        await commit_import_batch(db, owner, workspace.id, preview.id)


async def test_identifier_import_without_successful_lookups_is_failed(persistence_db, monkeypatch):
    db = persistence_db
    owner, workspace = await _owner(db)
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda settings: provider_runtime(
            settings=settings,
            transport=httpx2.MockTransport(lambda _request: httpx2.Response(503)),
        ),
    )
    preview = await stage_identifiers_import_batch(
        db, owner, workspace.id, ["10.1234/unavailable"], "doi"
    )
    assert preview.status == "failed" and preview.records == ()
    assert [diagnostic.code for diagnostic in preview.errors] == ["provider_unavailable"]
    assert (await get_import_batch_preview(db, owner, workspace.id, preview.id)).status == "failed"


async def test_pdf_preparation_without_candidates_preserves_sources_for_retry(
    persistence_db, fake_durable_operations
):
    db = persistence_db
    owner, workspace = await _owner(db)
    store = get_object_store()
    source = await store.put_object(uuid4(), ObjectSuffix.PDF, b"%PDF-invalid", max_bytes=20)
    workflow_id = f"prepare-pdf-import:{uuid4()}"
    batch = ImportBatch(
        workspace_id=workspace.id,
        actor_id=owner.id,
        file_format="pdf",
        status=ImportBatchStatus.pending,
        records=[],
        errors=[],
        staged_files=[
            FileObject(
                backend="documents",
                filename=source.key,
                size=source.size,
                content_type="application/pdf",
                metadata={"original_name": "invalid.pdf", "source_id": str(uuid4()), "row": 1},
            )
        ],
        workflow_id=workflow_id,
    )
    db.add(batch)
    await db.commit()
    assert await finalize_pdf_import_batch(
        db,
        owner.id,
        workspace.id,
        batch.id,
        workflow_id,
        [],
        [{"code": "invalid_pdf", "message": "PDF is unreadable", "row": 1}],
    )
    await db.commit()
    preview = await get_import_batch_preview(db, owner, workspace.id, batch.id)
    assert preview.status == "failed" and preview.records == ()
    assert preview.errors[0].code == "invalid_pdf"
    owner_id, workspace_id, batch_id = owner.id, workspace.id, batch.id
    await delete_unreferenced_objects(db, [source.key])
    assert await store.exists(source.key)
    owner = await db.get(User, owner_id)
    retried = await retry_pdf_import_batch(db, owner, workspace_id, batch_id)
    assert retried.status == "pending" and retried.workflow_id != workflow_id
    assert not await finalize_pdf_import_batch(
        db, owner_id, workspace_id, batch_id, workflow_id, [], []
    )


async def test_import_expiration_uses_latest_state_change_and_preserves_committed_documents(
    persistence_db,
):
    db = persistence_db
    owner, workspace = await _owner(db)
    preview = await _preview(db, owner, workspace.id, "Receipt expires, Item remains")
    receipt = await commit_import_batch(db, owner, workspace.id, preview.id)
    old = datetime.now(UTC) - timedelta(days=8)
    recent = await _preview(db, owner, workspace.id, "Recently changed")
    recent_batch = await db.get(ImportBatch, recent.id)
    recent_batch.created_at = old
    batch = await db.get(ImportBatch, receipt.id)
    batch.updated_at = old
    revision = FileRevision(
        workspace_id=workspace.id,
        item_id=receipt.committed_item_ids[0],
        created_by=owner.id,
        file=FileObject(
            backend="documents",
            filename=f"{uuid4()}.pdf",
            size=10,
            content_type="application/pdf",
            metadata={"original_name": "retained.pdf"},
        ),
    )
    db.add(revision)
    await db.commit()
    before = datetime.now(UTC) - timedelta(days=7)
    original_updated_at = recent_batch.updated_at
    await get_import_batch_preview(db, owner, workspace.id, recent.id)
    await list_import_batches(db, owner, workspace.id)
    assert recent_batch.updated_at == original_updated_at
    count, cursor = await purge_expired_import_batches(db, before=before)
    assert count == 1 and cursor == receipt.id
    assert await db.get(ImportBatch, receipt.id) is None
    assert await db.get(ImportBatch, recent.id) is not None
    assert await db.get(Item, receipt.committed_item_ids[0]) is not None
    assert await db.get(FileRevision, revision.id) is revision
    # The owner does not commit: its caller can roll back the whole retirement.
    await db.rollback()
    assert await db.get(ImportBatch, receipt.id) is not None


@pytest.mark.parametrize(
    ("raw_status", "state", "expires"),
    [
        ("ENQUEUED", "pending", False),
        ("PENDING", "running", False),
        ("SUCCESS", "succeeded", True),
        ("ERROR", "failed", True),
        ("CANCELLED", "cancelled", True),
        ("MAX_RECOVERY_ATTEMPTS_EXCEEDED", "failed", True),
        ("FUTURE_SDK_STATE", "failed", False),
        (None, None, True),
        ("lookup_error", "failed", False),
    ],
)
async def test_import_expiration_protects_active_and_unknown_pdf_preparation(
    persistence_db, fake_durable_operations, monkeypatch, raw_status, state, expires
):
    db = persistence_db
    owner, workspace = await _owner(db)
    store = get_object_store()
    source = await store.put_object(uuid4(), ObjectSuffix.PDF, b"%PDF-retained", max_bytes=20)
    workflow_id = f"prepare-pdf-import:{uuid4()}"
    batch = ImportBatch(
        workspace_id=workspace.id,
        actor_id=owner.id,
        file_format="pdf",
        status=ImportBatchStatus.pending,
        records=[],
        errors=[],
        staged_files=[
            FileObject(
                backend="documents",
                filename=source.key,
                size=source.size,
                content_type="application/pdf",
                metadata={"original_name": "pending.pdf", "source_id": str(uuid4())},
            )
        ],
        workflow_id=workflow_id,
        updated_at=datetime.now(UTC) - timedelta(days=8),
    )
    db.add(batch)
    await db.commit()
    if raw_status:
        await fake_durable_operations.enqueue(
            "library.prepare_pdf_import", queue_name="library.import", workflow_id=workflow_id
        )
        workflow = fake_durable_operations.workflows[workflow_id]
        fake_durable_operations.workflows[workflow_id] = replace(
            workflow, state=state, raw_status=raw_status
        )
    if raw_status == "lookup_error":
        monkeypatch.setattr(
            fake_durable_operations,
            "get",
            AsyncMock(side_effect=RuntimeError("workflow store unavailable")),
        )
    count, cursor = await purge_expired_import_batches(
        db, before=datetime.now(UTC) - timedelta(days=7)
    )
    await db.commit()
    assert count == int(expires) and cursor == batch.id
    assert (await db.get(ImportBatch, batch.id) is None) == expires
    cleanup = [
        enqueue
        for enqueue in fake_durable_operations.enqueues
        if (enqueue["attributes"] or {}).get("operation") == "import_batch_expire"
    ]
    assert len(cleanup) == int(expires)
    if expires:
        assert cleanup[0]["args"][2] == [source.key]
        # An obsolete completion cannot recreate a retired batch or publish Items.
        assert not await finalize_pdf_import_batch(
            db, owner.id, workspace.id, batch.id, workflow_id, [], []
        )
    await delete_unreferenced_objects(db, [source.key])
    assert await store.exists(source.key) == (not expires)


async def test_import_expiration_scans_past_protected_batches(
    persistence_db, fake_durable_operations
):
    db = persistence_db
    owner, workspace = await _owner(db)
    first = await _preview(db, owner, workspace.id, "Still preparing")
    later = await _preview(db, owner, workspace.id, "Expired ready")
    active = await db.get(ImportBatch, first.id)
    active.file_format = "pdf"
    active.status = ImportBatchStatus.pending
    active.workflow_id = "retention-active-first"
    await fake_durable_operations.enqueue(
        "library.prepare_pdf_import", queue_name="library.import", workflow_id=active.workflow_id
    )
    ready = await db.get(ImportBatch, later.id)
    old = datetime.now(UTC) - timedelta(days=8)
    active.updated_at = ready.updated_at = old
    await db.commit()
    before = datetime.now(UTC) - timedelta(days=7)
    assert await purge_expired_import_batches(db, before=before, limit=1) == (0, first.id)
    assert await purge_expired_import_batches(db, before=before, limit=1, after=first.id) == (
        1,
        later.id,
    )
    assert await purge_expired_import_batches(db, before=before, limit=1, after=later.id) == (
        0,
        None,
    )


async def test_expired_staging_cleanup_ignores_actor_authority_and_protects_other_batches(
    persistence_db,
):
    db = persistence_db
    owner, workspace = await _owner(db)
    source = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-shared-source", max_bytes=30
    )
    old = datetime.now(UTC) - timedelta(days=8)
    batches = []
    for status, changed_at in ((ImportBatchStatus.failed, old), (ImportBatchStatus.ready, None)):
        batch = ImportBatch(
            workspace_id=workspace.id,
            actor_id=owner.id,
            file_format="pdf",
            status=status,
            records=[],
            errors=[],
            staged_files=[
                FileObject(
                    backend="documents",
                    filename=source.key,
                    size=source.size,
                    content_type="application/pdf",
                    metadata={"original_name": "shared.pdf", "source_id": str(uuid4())},
                )
            ],
        )
        if changed_at:
            batch.updated_at = changed_at
        db.add(batch)
        batches.append(batch)
    owner.active = False
    workspace.governance_frozen_at = datetime.now(UTC)
    await db.commit()
    old_id, recent_id = (batch.id for batch in batches)
    before = datetime.now(UTC) - timedelta(days=7)
    assert await purge_expired_import_batches(db, before=before) == (1, old_id)
    await db.commit()
    await delete_unreferenced_objects(db, [source.key])
    assert await get_object_store().exists(source.key)
    recent = await db.get(ImportBatch, recent_id)
    recent.updated_at = old
    await db.commit()
    assert await purge_expired_import_batches(db, before=before) == (1, recent_id)
    await db.commit()
    await delete_unreferenced_objects(db, [source.key])
    assert not await get_object_store().exists(source.key)
