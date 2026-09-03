from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from quirebase.core import workflows
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.documents import workflows as document_workflows
from quirebase.library import workflows as library_workflows
from quirebase.models import FileRevision, Item, User
from quirebase.operations import health
from quirebase.operations import workflows as operation_workflows


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
async def test_child_workflow_enqueue_uses_core_options(monkeypatch):
    enqueued = []

    async def enqueue(options, *args):
        await asyncio.sleep(0)
        enqueued.append((options, args))
        return SimpleNamespace(get_workflow_id=lambda: options["workflow_id"])

    monkeypatch.setattr(workflows.DBOS, "enqueue_workflow_with_options_async", enqueue)

    workflow_id = await workflows.enqueue_child_workflow(
        "library.file_revision_changed",
        "item-id",
        "owner-id",
        queue_name=workflows.LIBRARY_QUEUE,
        workflow_id="file-revision-changed:revision-id",
        attributes={"capability": "library"},
    )

    assert workflow_id == "file-revision-changed:revision-id"
    assert enqueued == [
        (
            {
                "workflow_name": "library.file_revision_changed",
                "queue_name": workflows.LIBRARY_QUEUE,
                "workflow_id": "file-revision-changed:revision-id",
                "application_name": "quirebase",
                "attributes": {"capability": "library"},
            },
            ("item-id", "owner-id"),
        )
    ]


def test_library_workflow_uses_documents_owned_file_revision_changed_contract():
    assert (
        document_workflows.FILE_REVISION_CHANGED_WORKFLOW
        == library_workflows.FILE_REVISION_CHANGED_WORKFLOW
    )


def test_periodic_maintenance_uses_managed_dbos_schedule():
    assert operation_workflows.maintenance_schedules() == [
        {
            "schedule_name": "operations.periodic_maintenance.hourly",
            "workflow_fn": operation_workflows.periodic_maintenance_workflow,
            "schedule": "0 * * * *",
            "context": None,
            "automatic_backfill": False,
            "queue_name": workflows.OPERATIONS_QUEUE,
        }
    ]


@pytest.mark.anyio
async def test_unknown_workflow_id_is_reported_as_absent(monkeypatch):
    from dbos import error

    from quirebase.core.workflows import DBOSAdapter

    class MissingClient:
        async def retrieve_workflow_async(self, workflow_id):
            raise error.DBOSNonExistentWorkflowError("target", workflow_id)

    adapter = DBOSAdapter(MissingClient())
    assert await adapter.get("does-not-exist") is None


@pytest.mark.anyio
async def test_workflow_state_counts_use_database_aggregation():
    from quirebase.core.workflows import DBOSAdapter

    class AggregateDatabase:
        def __init__(self):
            self.options = None

        def get_workflow_aggregates(self, **options):
            self.options = options
            return [
                {"group": {"status": "SUCCESS"}, "count": 7},
                {"group": {"status": "ERROR"}, "count": 2},
                {"group": {"status": "MAX_RECOVERY_ATTEMPTS_EXCEEDED"}, "count": 1},
                {"group": {"status": "ENQUEUED"}, "count": 3},
            ]

    database = AggregateDatabase()
    client = SimpleNamespace(_sys_db=database)

    assert await DBOSAdapter(client).state_counts() == {
        "succeeded": 7,
        "failed": 3,
        "pending": 3,
    }
    assert database.options == {
        "group_by_status": True,
        "select_count": True,
        "application_name": ["quirebase"],
    }


@pytest.mark.anyio
async def test_system_metrics_use_aggregate_workflow_counts(async_db, monkeypatch):
    admin = User(
        username="workflow-metrics-admin",
        password_hash="unused",
        role="administrator",
    )
    async_db.add(admin)
    await async_db.commit()

    class CountsOnly:
        async def state_counts(self):
            await asyncio.sleep(0)
            return {"pending": 4, "failed": 2}

        async def list(self, **_options):
            raise AssertionError("metrics must not load workflow history")

    monkeypatch.setattr(health, "durable_operations", lambda: CountsOnly())

    metrics = await health.get_system_metrics(async_db, admin)

    assert 'quirebase_workflows{state="failed"} 2' in metrics
    assert 'quirebase_workflows{state="pending"} 4' in metrics


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

    async def enqueue(revision_id, item_id, owner_id):
        await asyncio.sleep(0)
        enqueued.append((revision_id, item_id, owner_id))
        return f"file-revision-changed:{revision_id}"

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
    monkeypatch.setattr(document_workflows, "_enqueue_file_revision_changed", enqueue)

    workflow_body = document_workflows.inspect_imported_revision_workflow.__wrapped__.__wrapped__
    await workflow_body(revision.id, user.id, stored.key, str(uuid4()))

    assert enqueued == [(revision.id, item.id, user.id)]


@pytest.mark.anyio
async def test_imported_revision_keeps_thumbnail_after_database_commit(monkeypatch):
    removed = []

    async def inspect(*_args):
        await asyncio.sleep(0)
        return {"revision_id": "revision-id"}

    async def commit(_inspected):
        await asyncio.sleep(0)
        return {"revision_id": "revision-id", "item_id": "item-id"}

    async def fail_to_enqueue(*_args):
        await asyncio.sleep(0)
        raise RuntimeError("temporary DBOS failure")

    async def remove(key):
        await asyncio.sleep(0)
        removed.append(key)

    monkeypatch.setattr(document_workflows, "inspect_imported_pdf", inspect)
    monkeypatch.setattr(document_workflows, "commit_imported_revision", commit)
    monkeypatch.setattr(document_workflows, "_enqueue_file_revision_changed", fail_to_enqueue)
    monkeypatch.setattr(document_workflows, "remove_owned_object", remove)
    workflow_body = document_workflows.inspect_imported_revision_workflow.__wrapped__.__wrapped__

    with pytest.raises(RuntimeError, match="temporary DBOS failure"):
        await workflow_body(
            "revision-id",
            "owner-id",
            "aa/bb/imported.pdf",
            "00000000-0000-0000-0000-000000000001",
        )

    assert removed == []


@pytest.mark.anyio
async def test_periodic_maintenance_workflow_uses_dbos_steps(monkeypatch):
    calls = []

    async def cleanup():
        await asyncio.sleep(0)
        calls.append("cleanup")
        return 2

    async def scan():
        await asyncio.sleep(0)
        calls.append("scan")
        return {
            "errors": [],
            "deleted_orphans": ["orphan"],
            "checked_status": "ok",
        }

    monkeypatch.setattr(operation_workflows, "cleanup_exports_step", cleanup)
    monkeypatch.setattr(operation_workflows, "_run_integrity_scan", scan)

    workflow_body = operation_workflows.periodic_maintenance_workflow.__wrapped__.__wrapped__
    result = await workflow_body(datetime.now(UTC), None)

    assert result is None
    assert calls == ["cleanup", "scan"]


@pytest.mark.anyio
async def test_datasource_step_writes_checkpoint_in_datasource_outputs(async_db, tmp_path):
    from dbos import DBOS, DBOSConfig
    from sqlalchemy import text

    from quirebase.core.workflows import ads

    sys_db = tmp_path / "sys.db"
    DBOS(config=DBOSConfig(name="test_app", system_database_url=f"sqlite:///{sys_db}"))
    DBOS.launch()

    @ads.transaction()
    async def sample_step(value: int) -> int:
        session = ads.sql_session()
        await session.execute(text("SELECT :v"), {"v": value})
        return value * 2

    @DBOS.workflow()
    async def sample_workflow(value: int) -> int:
        return await sample_step(value)

    try:
        result = await sample_workflow(21)
        assert result == 42
        outputs = (
            await async_db.execute(
                text("SELECT workflow_id, step_id, output FROM datasource_outputs")
            )
        ).fetchall()
        assert len(outputs) == 1
        assert outputs[0][1] == 1
    finally:
        DBOS.destroy()


@pytest.mark.anyio
async def test_commit_uploaded_revision_uses_datasource_transaction(async_db):
    user = User(username="upload-tx-user", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    item = Item(title="TX Item", created_by=user.id)
    async_db.add(item)
    await async_db.commit()

    rev_id = str(uuid4())
    inspected = {
        "revision_id": rev_id,
        "object_key": "aa/bb/doc.pdf",
        "thumbnail_object_key": "aa/bb/thumb.png",
        "thumbnail_size": 128,
        "size": 1024,
        "page_count": 2,
        "full_text": "Extracted text content",
        "page_geometry": "[]",
    }
    result = await document_workflows.commit_uploaded_revision(
        item.id, user.id, "my_doc.pdf", inspected
    )
    assert result == {"revision_id": rev_id, "item_id": item.id}

    saved = await async_db.get(FileRevision, rev_id)
    assert saved is not None
    assert saved.object_key == "aa/bb/doc.pdf"
    assert saved.page_count == 2
    assert saved.full_text == "Extracted text content"


@pytest.mark.anyio
async def test_commit_uploaded_attachment_uses_datasource_transaction(async_db):
    from quirebase.models import Attachment

    user = User(username="att-tx-user", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    item = Item(title="Attachment Item", created_by=user.id)
    async_db.add(item)
    await async_db.commit()

    att_id = str(uuid4())
    receipt = {"object_key": "aa/bb/data.bin", "size": 256}
    result = await document_workflows.commit_uploaded_attachment(
        item.id, user.id, att_id, "data.bin", "application/octet-stream", None, receipt
    )
    assert result == {"attachment_id": att_id, "item_id": item.id}

    saved = await async_db.get(Attachment, att_id)
    assert saved is not None
    assert saved.object_key == "aa/bb/data.bin"
    assert saved.size == 256


@pytest.mark.anyio
async def test_operations_and_library_transaction_steps(async_db):
    user = User(username="op-tx-user", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    item = Item(title="Reindex Item", created_by=user.id)
    async_db.add(item)
    await async_db.commit()

    reindex_res = await operation_workflows.reindex_all_step()
    assert reindex_res["reindexed_items"] >= 1

    await library_workflows.apply_file_revision_changed(item.id)


@pytest.mark.anyio
async def test_file_revision_change_retries_only_the_recommendation_request(monkeypatch):
    calls = []

    async def index(item_id):
        await asyncio.sleep(0)
        calls.append(("index", item_id))

    async def request(item_id, owner_id):
        await asyncio.sleep(0)
        calls.append(("request", item_id, owner_id))

    monkeypatch.setattr(library_workflows, "apply_file_revision_changed", index)
    monkeypatch.setattr(library_workflows, "request_item_tag_recommendation_step", request)

    workflow_body = library_workflows.file_revision_changed_workflow.__wrapped__.__wrapped__
    await workflow_body("item-id", "owner-id")

    assert calls == [
        ("index", "item-id"),
        ("request", "item-id", "owner-id"),
    ]


@pytest.mark.anyio
async def test_recommendation_workflow_computes_outside_datasource_transaction(monkeypatch):
    calls = []
    candidates = {"single_words": ["graph"], "phrases": ["graph model"]}

    async def generate(*_args):
        await asyncio.sleep(0)
        calls.append("generate")
        return candidates

    async def commit(item_id, generation_token, workflow_id, result):
        await asyncio.sleep(0)
        calls.append(("commit", item_id, generation_token, workflow_id, result))
        return {"single_words": 1, "phrases": 1}

    async def is_current(*_args):
        await asyncio.sleep(0)
        calls.append("check")
        return True

    monkeypatch.setattr(library_workflows, "item_tag_recommendation_is_current_step", is_current)
    monkeypatch.setattr(library_workflows, "generate_item_tag_recommendation_step", generate)
    monkeypatch.setattr(library_workflows, "commit_item_tag_recommendation_step", commit)

    workflow_body = library_workflows.recommend_tags_workflow.__wrapped__.__wrapped__
    result = await workflow_body("item-id", 2, "workflow-id")

    assert result == {"single_words": 1, "phrases": 1}
    assert calls == [
        "check",
        "generate",
        (
            "commit",
            "item-id",
            2,
            "workflow-id",
            candidates,
        ),
    ]


@pytest.mark.anyio
async def test_stale_recommendation_workflow_skips_inference(monkeypatch):
    async def is_current(*_args):
        await asyncio.sleep(0)
        return False

    async def unexpected_generate(*_args):
        await asyncio.sleep(0)
        raise AssertionError("stale workflow must not run inference")

    monkeypatch.setattr(library_workflows, "item_tag_recommendation_is_current_step", is_current)
    monkeypatch.setattr(
        library_workflows, "generate_item_tag_recommendation_step", unexpected_generate
    )

    workflow_body = library_workflows.recommend_tags_workflow.__wrapped__.__wrapped__
    assert await workflow_body("item-id", 1, "workflow-id") == {"stale": True}


@pytest.mark.anyio
async def test_recommend_all_uses_one_transaction_per_item(monkeypatch):
    requested = []

    async def list_items():
        await asyncio.sleep(0)
        return ("item-a", "item-b")

    async def request(item_id, owner_id):
        await asyncio.sleep(0)
        requested.append((item_id, owner_id))
        return True

    monkeypatch.setattr(operation_workflows, "list_items_for_tag_recommendation_step", list_items)
    monkeypatch.setattr(operation_workflows, "request_item_tag_recommendation_step", request)

    workflow_body = operation_workflows.recommend_tags_all_workflow.__wrapped__.__wrapped__
    result = await workflow_body("workflow-id", "owner-id")

    assert result == {"enqueued_items": 2}
    assert requested == [("item-a", "owner-id"), ("item-b", "owner-id")]


@pytest.mark.anyio
async def test_recommend_all_continues_when_snapshot_item_was_deleted(monkeypatch):
    requested = []

    async def list_items():
        await asyncio.sleep(0)
        return ("deleted-item", "live-item")

    async def request(item_id, _owner_id):
        await asyncio.sleep(0)
        requested.append(item_id)
        return item_id == "live-item"

    monkeypatch.setattr(operation_workflows, "list_items_for_tag_recommendation_step", list_items)
    monkeypatch.setattr(operation_workflows, "request_item_tag_recommendation_step", request)

    workflow_body = operation_workflows.recommend_tags_all_workflow.__wrapped__.__wrapped__
    assert await workflow_body("workflow-id", "owner-id") == {"enqueued_items": 1}
    assert requested == ["deleted-item", "live-item"]
