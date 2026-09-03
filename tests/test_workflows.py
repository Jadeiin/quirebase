from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from quirebase.core import workflows
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.documents import enqueue_object_cleanup
from quirebase.documents import workflows as document_workflows
from quirebase.library import workflows as library_workflows
from quirebase.models import (
    ExportArtifact,
    FileRevision,
    ImportBatch,
    Item,
    ObjectIntegrityScan,
    User,
)
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
async def test_object_cleanup_uses_non_partitioned_cleanup_queue(async_db, fake_durable_operations):
    await enqueue_object_cleanup(
        async_db,
        ["aa/bb/object.pdf"],
        owner_id="owner-id",
        operation="test_cleanup",
    )

    enqueue = fake_durable_operations.enqueues[-1]
    assert enqueue["queue_name"] == workflows.DOCUMENT_CLEANUP_QUEUE
    assert enqueue["partition_key"] is None


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
async def test_worker_registers_partitioned_revision_and_independent_workload_queues(monkeypatch):
    registrations = []

    class FakeDBOS:
        def __init__(self, **_config):
            pass

        @staticmethod
        def launch():
            return None

        @staticmethod
        async def register_queue_async(name, **options):
            registrations.append((name, options))

    class FakeDatasource:
        @staticmethod
        async def create(*_args, **_kwargs):
            return object()

    monkeypatch.setattr(workflows, "DBOS", FakeDBOS)
    monkeypatch.setattr(workflows, "AsyncSQLAlchemyDatasource", FakeDatasource)

    try:
        await workflows._launch_runtime("test-worker")
    finally:
        workflows.ads.set_instance(None)

    configured = dict(registrations)
    assert configured[workflows.DOCUMENTS_QUEUE] == {
        "worker_concurrency": 2,
        "global_concurrency": 4,
        "partition_concurrency": 1,
    }
    assert configured[workflows.DOCUMENT_CLEANUP_QUEUE] == {"worker_concurrency": 2}
    assert configured[workflows.RECOMMENDATION_QUEUE] == {"global_concurrency": 1}


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
async def test_active_workflow_query_filters_in_dbos_system_database():
    from quirebase.core.workflows import DBOSAdapter

    class ListingClient:
        def __init__(self):
            self.options = None

        async def list_workflows_async(self, **options):
            self.options = options
            return []

    client = ListingClient()
    assert await DBOSAdapter(client).list_active(name="documents.upload_revision") == ()
    assert client.options == {
        "status": ["ENQUEUED", "DELAYED", "PENDING"],
        "name": "documents.upload_revision",
        "limit": 100,
        "offset": 0,
        "sort_desc": True,
        "load_input": False,
        "load_output": False,
        "application_name": "quirebase",
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

    monkeypatch.setattr(operation_workflows, "_run_export_cleanup", cleanup)
    monkeypatch.setattr(operation_workflows, "_run_integrity_scan", scan)

    workflow_body = operation_workflows.periodic_maintenance_workflow.__wrapped__.__wrapped__
    result = await workflow_body(datetime.now(UTC), None)

    assert result is None
    assert calls == ["cleanup", "scan"]


@pytest.mark.anyio
async def test_export_cleanup_checkpoints_expired_artifacts_in_bounded_batches(monkeypatch):
    artifacts = [
        {"workflow_id": f"export-{index:03d}", "object_key": f"aa/bb/{index:03d}.pdf"}
        for index in range(101)
    ]
    listed = 0
    deleted_batches = []
    removed_batches = []

    async def get_ttl():
        await asyncio.sleep(0)
        return 24

    async def cleanup_local(_ttl_hours):
        await asyncio.sleep(0)
        return 0

    async def list_expired(limit):
        nonlocal listed
        await asyncio.sleep(0)
        page = tuple(artifacts[listed : listed + limit])
        listed += len(page)
        return page

    async def delete_objects(page):
        await asyncio.sleep(0)
        deleted_batches.append(tuple(row["workflow_id"] for row in page))
        return {
            "workflow_ids": [row["workflow_id"] for row in page],
            "removed": len(page),
        }

    async def delete_records(workflow_ids):
        await asyncio.sleep(0)
        removed_batches.append(tuple(workflow_ids))
        return len(workflow_ids)

    monkeypatch.setattr(operation_workflows, "cleanup_exports_step", cleanup_local)
    monkeypatch.setattr(operation_workflows, "get_export_ttl_step", get_ttl)
    monkeypatch.setattr(operation_workflows, "list_expired_export_artifacts_step", list_expired)
    monkeypatch.setattr(operation_workflows, "delete_export_artifact_objects_step", delete_objects)
    monkeypatch.setattr(operation_workflows, "delete_export_artifact_records_step", delete_records)

    assert await operation_workflows._run_export_cleanup() == 101
    assert [len(page) for page in deleted_batches] == [100, 1]
    assert removed_batches == deleted_batches


@pytest.mark.anyio
async def test_annotation_export_workflow_records_expiring_artifact(monkeypatch):
    result = {
        "filename": "artifact.pdf",
        "object_key": "aa/bb/artifact.pdf",
        "size_bytes": 42,
        "revision_id": "revision-id",
        "project_id": None,
    }
    recorded = []

    async def build(*_args):
        await asyncio.sleep(0)
        return result

    async def record(workflow_id, artifact):
        await asyncio.sleep(0)
        recorded.append((workflow_id, artifact))

    monkeypatch.setattr(document_workflows, "build_annotation_export", build)
    monkeypatch.setattr(document_workflows, "record_annotation_export_artifact", record)
    monkeypatch.setattr(document_workflows.DBOS, "workflow_id", "workflow-id")
    workflow_body = document_workflows.annotation_export_workflow.__wrapped__.__wrapped__

    output = await workflow_body(
        "owner-id",
        "revision-id",
        "00000000-0000-0000-0000-000000000001",
        None,
        True,
        "UTC",
    )

    assert output == result
    assert recorded == [("workflow-id", result)]


@pytest.mark.anyio
async def test_annotation_export_artifact_transaction_records_lifetime(async_db, monkeypatch):
    async def one_hour(*_args, **_kwargs):
        await asyncio.sleep(0)
        return 1

    monkeypatch.setattr("quirebase.operations.settings.get_effective_setting", one_hour)
    before = datetime.now(UTC)
    await document_workflows.record_annotation_export_artifact(
        "workflow-id",
        {
            "filename": "artifact.pdf",
            "object_key": "aa/bb/artifact.pdf",
            "size_bytes": 42,
            "revision_id": "revision-id",
            "project_id": None,
        },
    )

    artifact = await async_db.get(ExportArtifact, "workflow-id")
    assert artifact is not None
    assert artifact.object_key == "aa/bb/artifact.pdf"
    assert artifact.filename == "artifact.pdf"
    assert artifact.size == 42
    assert artifact.expires_at.replace(tzinfo=UTC) >= before + timedelta(minutes=59)


@pytest.mark.anyio
async def test_integrity_scan_applies_database_backfills_in_datasource_transaction(
    async_db, async_session_factory, monkeypatch
):
    user = User(username="integrity-owner", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    item = Item(title="Integrity transaction", created_by=user.id)
    async_db.add(item)
    await async_db.flush()
    pdf = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-integrity", max_bytes=100
    )
    thumbnail = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"thumbnail", max_bytes=100
    )
    revision = FileRevision(
        item_id=item.id,
        object_key=pdf.key,
        size=pdf.size,
        thumbnail_object_key=thumbnail.key,
        thumbnail_size=None,
        original_name="integrity.pdf",
        created_by=user.id,
    )
    async_db.add(revision)
    await async_db.commit()
    monkeypatch.setattr(operation_workflows, "AsyncSessionLocal", async_session_factory)

    report = await operation_workflows.scan_objects_step()

    await async_db.refresh(revision)
    assert revision.thumbnail_size is None
    assert report["thumbnail_sizes"] == {revision.id: thumbnail.size}

    await operation_workflows.record_integrity_scan_step(
        report["errors"], report["thumbnail_sizes"]
    )
    await async_db.refresh(revision)
    assert revision.thumbnail_size == thumbnail.size
    assert await async_db.get(ObjectIntegrityScan, "latest") is not None


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
async def test_datasource_transaction_default_name_is_fully_qualified(monkeypatch):
    captured = []

    async def run(options, function, *args, **kwargs):
        captured.append(options)
        return await function(*args, **kwargs)

    async def duplicate_step() -> int:
        await asyncio.sleep(0)
        return 1

    duplicate_step.__module__ = "quirebase.example"
    wrapped = workflows.ads.transaction()(duplicate_step)
    monkeypatch.setattr(workflows.ads, "run_tx_step_async", run)

    assert await wrapped() == 1
    assert captured == [
        {
            "name": "quirebase.example.test_datasource_transaction_default_name_is_fully_qualified.<locals>.duplicate_step",
            "isolation_level": "SERIALIZABLE",
        }
    ]


@pytest.mark.anyio
async def test_read_heavy_datasource_steps_use_read_committed(monkeypatch):
    captured = []

    async def run(options, _function, *_args, **_kwargs):
        await asyncio.sleep(0)
        captured.append(options)

    monkeypatch.setattr(workflows.ads, "run_tx_step_async", run)
    await operation_workflows.list_reindex_item_ids_step(None, 100)
    await operation_workflows.record_integrity_scan_step([], {})
    await operation_workflows.list_items_for_tag_recommendation_step(None, 100)
    await operation_workflows.get_export_ttl_step()
    await library_workflows.item_tag_recommendation_is_current_step("item-id", 1, "workflow-id")

    assert {options["isolation_level"] for options in captured} == {"READ COMMITTED"}


@pytest.mark.anyio
async def test_search_projection_writes_use_serializable(monkeypatch):
    captured = []

    async def run(options, _function, *_args, **_kwargs):
        await asyncio.sleep(0)
        captured.append(options)

    monkeypatch.setattr(workflows.ads, "run_tx_step_async", run)
    await operation_workflows.reindex_items_step(())
    await library_workflows.apply_file_revision_changed("item-id")

    assert {options["isolation_level"] for options in captured} == {"SERIALIZABLE"}


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

    reindex_res = await operation_workflows.reindex_all_workflow.__wrapped__.__wrapped__(
        "workflow-id", "owner-id"
    )
    assert reindex_res["reindexed_items"] >= 1

    await library_workflows.apply_file_revision_changed(item.id)


@pytest.mark.anyio
async def test_reindex_workflow_checkpoints_bounded_database_batches(monkeypatch):
    item_ids = [f"item-{index:03d}" for index in range(101)]
    indexed_batches = []

    async def list_ids(after_id, limit):
        await asyncio.sleep(0)
        start = 0 if after_id is None else item_ids.index(after_id) + 1
        return tuple(item_ids[start : start + limit])

    async def index_ids(batch):
        await asyncio.sleep(0)
        indexed_batches.append(tuple(batch))
        return len(batch)

    monkeypatch.setattr(operation_workflows, "list_reindex_item_ids_step", list_ids)
    monkeypatch.setattr(operation_workflows, "reindex_items_step", index_ids)
    workflow_body = operation_workflows.reindex_all_workflow.__wrapped__.__wrapped__

    result = await workflow_body("workflow-id", "owner-id")

    assert result == {"reindexed_items": 101}
    assert [len(batch) for batch in indexed_batches] == [100, 1]


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
async def test_pdf_import_workflow_marks_batch_failed_and_preserves_pdf(async_db, monkeypatch):
    user = User(username="failed-import-owner", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    stored = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-retry", max_bytes=100
    )
    pending = {
        "_row": 1,
        "_pdf": {
            "object_key": stored.key,
            "size": stored.size,
            "original_name": "retry.pdf",
        },
    }
    batch = ImportBatch(
        owner_id=user.id,
        file_format="pdf",
        records=json.dumps([pending]),
        errors="[]",
        status="pending",
        workflow_id="prepare-pdf-import:failed",
    )
    async_db.add(batch)
    await async_db.commit()

    async def exhausted(*_args):
        await asyncio.sleep(0)
        raise RuntimeError("provider retries exhausted")

    async def extracted(*_args):
        await asyncio.sleep(0)
        return {
            "detected_doi": "10.1000/retry",
            "normalized_doi": "10.1000/retry",
            "object_key": stored.key,
        }

    async def eligible(*_args):
        await asyncio.sleep(0)
        return {"eligible": True, "object_key": stored.key}

    monkeypatch.setattr(library_workflows, "extract_pdf_import_doi_step", extracted)
    monkeypatch.setattr(library_workflows, "check_pdf_import_doi_step", eligible)
    monkeypatch.setattr(library_workflows, "lookup_pdf_import_candidate_step", exhausted)
    workflow_body = library_workflows.prepare_pdf_import_workflow.__wrapped__.__wrapped__

    with pytest.raises(RuntimeError, match="provider retries exhausted"):
        await workflow_body(batch.id, batch.workflow_id, [pending])

    await async_db.refresh(batch)
    assert batch.status == "failed"
    assert await get_object_store().exists(stored.key)


@pytest.mark.anyio
async def test_pdf_import_workflow_checkpoints_extract_conflict_and_provider_lookup(monkeypatch):
    calls = []
    pending = {
        "_row": 1,
        "_pdf": {
            "object_key": "aa/bb/candidate.pdf",
            "size": 10,
            "original_name": "candidate.pdf",
        },
    }

    async def extract(candidate):
        await asyncio.sleep(0)
        calls.append(("extract", candidate["_row"]))
        return {
            "detected_doi": "10.1000/checkpointed",
            "normalized_doi": "10.1000/checkpointed",
            "object_key": candidate["_pdf"]["object_key"],
        }

    async def check(batch_id, candidate, detected_doi):
        await asyncio.sleep(0)
        calls.append(("check", batch_id, candidate["_row"], detected_doi))
        return {"eligible": True, "object_key": candidate["_pdf"]["object_key"]}

    async def lookup(batch_id, candidate, detected_doi):
        await asyncio.sleep(0)
        calls.append(("lookup", batch_id, candidate["_row"], detected_doi))
        return {
            "record": {"title": "Checkpointed", "_pdf": candidate["_pdf"]},
            "normalized_doi": detected_doi,
            "object_key": candidate["_pdf"]["object_key"],
        }

    async def finalize(*_args):
        await asyncio.sleep(0)
        return True

    monkeypatch.setattr(library_workflows, "extract_pdf_import_doi_step", extract)
    monkeypatch.setattr(library_workflows, "check_pdf_import_doi_step", check)
    monkeypatch.setattr(library_workflows, "lookup_pdf_import_candidate_step", lookup)
    monkeypatch.setattr(library_workflows, "finalize_pdf_import_batch_step", finalize)
    workflow_body = library_workflows.prepare_pdf_import_workflow.__wrapped__.__wrapped__

    result = await workflow_body("batch-id", "workflow-id", [pending])

    assert result == {"candidates": 1, "diagnostics": 0, "discarded": False}
    assert calls == [
        ("extract", 1),
        ("check", "batch-id", 1, "10.1000/checkpointed"),
        ("lookup", "batch-id", 1, "10.1000/checkpointed"),
    ]


@pytest.mark.anyio
async def test_recommend_all_uses_one_transaction_per_item(monkeypatch):
    requested = []

    async def list_items(_after_id, _limit):
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
async def test_recommend_all_checkpoints_bounded_keyset_pages(monkeypatch):
    item_ids = [f"item-{index:03d}" for index in range(101)]
    requested = []
    page_sizes = []

    async def list_items(after_id, limit):
        await asyncio.sleep(0)
        start = 0 if after_id is None else item_ids.index(after_id) + 1
        page = tuple(item_ids[start : start + limit])
        page_sizes.append(len(page))
        return page

    async def request(item_id, _owner_id):
        await asyncio.sleep(0)
        requested.append(item_id)
        return True

    monkeypatch.setattr(operation_workflows, "list_items_for_tag_recommendation_step", list_items)
    monkeypatch.setattr(operation_workflows, "request_item_tag_recommendation_step", request)
    workflow_body = operation_workflows.recommend_tags_all_workflow.__wrapped__.__wrapped__

    result = await workflow_body("workflow-id", "owner-id")

    assert result == {"enqueued_items": 101}
    assert page_sizes == [100, 1]
    assert requested == item_ids


@pytest.mark.anyio
async def test_recommend_all_continues_when_snapshot_item_was_deleted(monkeypatch):
    requested = []

    async def list_items(_after_id, _limit):
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
