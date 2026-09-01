from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from quirebase.core import workflows
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.documents import workflows as document_workflows
from quirebase.models import FileRevision, Item, User
from quirebase.operations import maintenance


@pytest.mark.parametrize(
    ("raw", "visible"),
    [
        ("ENQUEUED", "pending"),
        ("DELAYED", "pending"),
        ("PENDING", "running"),
        ("SUCCESS", "succeeded"),
        ("ERROR", "failed"),
        ("MAX_RECOVERY_ATTEMPTS_EXCEEDED", "failed"),
        ("CANCELLED", "cancelled"),
    ],
)
def test_dbos_statuses_have_a_stable_user_visible_mapping(raw, visible):
    status = SimpleNamespace(
        workflow_id="workflow-id",
        name="documents.upload_revision",
        status=raw,
        queue_name="documents.upload",
        executor_id=None,
        created_at=None,
        updated_at=None,
        output=None,
        error=None,
        attributes={},
        authenticated_user=None,
    )
    assert workflows._summary(status).state == visible


@pytest.mark.anyio
async def test_transactional_enqueue_records_queue_partition_and_attributes(
    async_db, fake_durable_operations
):
    workflow_id = await fake_durable_operations.enqueue_in_transaction(
        async_db,
        "documents.inspect_revision",
        "revision-id",
        queue_name=workflows.DOCUMENTS_QUEUE,
        workflow_id="workflow-id",
        partition_key="revision-id",
        attributes={"capability": "documents"},
    )
    summary = await fake_durable_operations.get(workflow_id)
    assert summary is not None
    assert summary.queue_name == workflows.DOCUMENTS_QUEUE
    assert summary.attributes == {"capability": "documents"}


@pytest.mark.anyio
async def test_unknown_workflow_id_is_reported_as_absent(monkeypatch):
    from dbos._error import DBOSNonExistentWorkflowError

    from quirebase.core.workflows import DBOSAdapter

    class MissingClient:
        async def retrieve_workflow_async(self, workflow_id):
            raise DBOSNonExistentWorkflowError("target", workflow_id)

    adapter = DBOSAdapter(MissingClient())
    assert await adapter.get("does-not-exist") is None


@pytest.mark.anyio
async def test_imported_revision_inspection_enqueues_derived_state_sync(
    async_db, async_session_factory, monkeypatch
):
    user = User(username="import-workflow-owner", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    item = Item(title="Imported PDF", created_by=user.id)
    async_db.add(item)
    await async_db.flush()
    stored = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-imported", max_bytes=100
    )
    revision = FileRevision(
        item_id=item.id,
        object_key=stored.key,
        size=stored.size,
        original_name="imported.pdf",
        created_by=user.id,
    )
    async_db.add(revision)
    await async_db.commit()

    enqueued = []

    async def enqueue(options, *args):
        await asyncio.sleep(0)
        enqueued.append((options, args))

    monkeypatch.setattr(document_workflows, "AsyncSessionLocal", async_session_factory)
    monkeypatch.setattr(document_workflows, "validate_pdf_container", lambda _source: None)
    monkeypatch.setattr(
        document_workflows, "inspect_pdf", lambda _source: (1, "extracted text", [])
    )
    monkeypatch.setattr(
        document_workflows,
        "create_thumbnail",
        lambda _source, destination: destination.write_bytes(b"thumbnail"),
    )
    monkeypatch.setattr(document_workflows.DBOS, "enqueue_workflow_with_options_async", enqueue)

    workflow_body = document_workflows.inspect_imported_revision_workflow.__wrapped__.__wrapped__
    await workflow_body(revision.id, user.id, stored.key, str(uuid4()))

    assert enqueued == [
        (
            {
                "workflow_name": document_workflows.FILE_REVISION_CHANGED_WORKFLOW,
                "queue_name": "library",
                "workflow_id": f"file-revision-changed:{revision.id}",
                "application_name": "quirebase",
            },
            (item.id, user.id),
        )
    ]


@pytest.mark.anyio
async def test_periodic_maintenance_cycle_cleans_exports_and_reconciles_objects(
    async_session_factory, monkeypatch
):
    calls = []

    async def cleanup(db):
        await asyncio.sleep(0)
        calls.append(("cleanup", db))

    async def reconcile(db):
        await asyncio.sleep(0)
        calls.append(("reconcile", db))

    monkeypatch.setattr("quirebase.core.database.AsyncSessionLocal", async_session_factory)
    monkeypatch.setattr(maintenance, "cleanup_exports", cleanup)
    monkeypatch.setattr(maintenance, "reconcile_objects", reconcile)

    await maintenance.run_maintenance_cycle()

    assert [name for name, _db in calls] == ["cleanup", "reconcile"]
    assert calls[0][1] is calls[1][1]
