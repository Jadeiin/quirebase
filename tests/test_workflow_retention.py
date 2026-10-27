from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from dbos import DBOS, DBOSConfig
from dbos._schemas import SCHEMA_PLACEHOLDER
from dbos._schemas.datasource_database import datasource_outputs_table
from dbos._schemas.system_database import SystemSchema
from sqlalchemy import delete, event, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from quirebase.core.workflow_storage import (
    purge_orphan_datasource_outputs,
    purge_workflow_history,
    workflow_storage_counts,
)
from quirebase.core.workflows import ads, enqueue_child_workflow
from quirebase.models import MaintenanceSnapshot
from quirebase.operations import workflows as maintenance

_DATASOURCE_OUTPUTS = datasource_outputs_table(SCHEMA_PLACEHOLDER)


@pytest.fixture
async def workflow_store(async_session_factory):
    engine = async_session_factory.kw["bind"]
    async with engine.begin() as connection:
        connection = await connection.execution_options(
            schema_translate_map={SCHEMA_PLACEHOLDER: None}
        )
        await connection.run_sync(SystemSchema.workflow_status.create)
        await connection.run_sync(SystemSchema.operation_outputs.create)
        await connection.run_sync(SystemSchema.workflow_input.create)
        await connection.run_sync(SystemSchema.workflow_output.create)
    return async_session_factory


@pytest.fixture
async def retention_race_store(persistence_sessions):
    """Exercise both dialects without starting DBOS or modifying existing SDK tables."""
    engine = persistence_sessions.kw["bind"]
    schema = None if engine.dialect.name == "sqlite" else "dbos"
    created = []
    prefix = f"retention-race-{uuid4()}"
    tables = (
        SystemSchema.workflow_status,
        SystemSchema.operation_outputs,
        SystemSchema.workflow_input,
        SystemSchema.workflow_output,
        _DATASOURCE_OUTPUTS,
    )
    async with engine.begin() as connection:
        connection = await connection.execution_options(
            schema_translate_map={SCHEMA_PLACEHOLDER: schema}
        )
        if schema:
            await connection.execute(text("CREATE SCHEMA IF NOT EXISTS dbos"))
        for table in tables:
            exists = await connection.run_sync(
                lambda sync, table=table: inspect(sync).has_table(table.name, schema=schema)
            )
            if not exists:
                await connection.run_sync(table.create)
                created.append(table)
    try:
        yield persistence_sessions, prefix
    finally:
        async with engine.begin() as connection:
            connection = await connection.execution_options(
                schema_translate_map={SCHEMA_PLACEHOLDER: schema}
            )
            await connection.execute(
                delete(_DATASOURCE_OUTPUTS).where(
                    _DATASOURCE_OUTPUTS.c.workflow_id.startswith(prefix)
                )
            )
            for table in (
                SystemSchema.operation_outputs,
                SystemSchema.workflow_input,
                SystemSchema.workflow_output,
            ):
                await connection.execute(
                    delete(table).where(table.c.workflow_uuid.startswith(prefix))
                )
            await connection.execute(
                delete(SystemSchema.workflow_status).where(
                    SystemSchema.workflow_status.c.workflow_uuid.startswith(prefix)
                )
            )
            for table in reversed(created):
                await connection.run_sync(table.drop)


async def _workflow(
    db, identity, *, status="SUCCESS", parent=None, age_days=8, owner="quirebase", completed=True
):
    instant = int((datetime.now(UTC) - timedelta(days=age_days)).timestamp() * 1000)
    connection = await db.connection()
    schema = None if connection.dialect.name == "sqlite" else "dbos"
    await connection.execution_options(schema_translate_map={SCHEMA_PLACEHOLDER: schema})
    await db.execute(
        SystemSchema.workflow_status.insert().values(
            workflow_uuid=identity,
            name="example",
            status=status,
            parent_workflow_id=parent,
            created_at=instant,
            updated_at=instant,
            completed_at=instant if completed else None,
            priority=0,
            application_name=owner,
        )
    )
    await db.execute(
        SystemSchema.operation_outputs.insert().values(
            workflow_uuid=identity,
            function_id=1,
            function_name="example",
            output="checkpoint",
            retention_timestamp=instant,
        )
    )
    await db.execute(
        SystemSchema.workflow_input.insert().values(
            workflow_uuid=identity, inputs="arguments", retention_timestamp=instant
        )
    )
    await db.execute(
        SystemSchema.workflow_output.insert().values(
            workflow_uuid=identity, output="result", retention_timestamp=instant
        )
    )
    await db.execute(
        _DATASOURCE_OUTPUTS.insert().values(
            workflow_id=identity, step_id=1, output="receipt", created_at=instant
        )
    )


@pytest.mark.anyio
async def test_retention_preserves_active_recent_foreign_and_retained_parent_children(
    workflow_store,
):
    async with workflow_store() as db, db.begin():
        await _workflow(db, "expired")
        await _workflow(db, "running", status="PENDING")
        await _workflow(db, "queued", status="ENQUEUED")
        await _workflow(db, "delayed", status="DELAYED")
        await _workflow(db, "unknown", status="FUTURE")
        await _workflow(db, "unconfirmed-completion", completed=False)
        await _workflow(db, "recent", age_days=1)
        await _workflow(db, "foreign", owner="other-app")
        # Native parent identity protects this child even before the SDK has
        # published the separate enqueue operation edge.
        await _workflow(db, "native-child", parent="running")
        await _workflow(db, "operation-child")
        await db.execute(
            SystemSchema.operation_outputs.insert().values(
                workflow_uuid="recent",
                function_id=2,
                function_name="enqueue",
                child_workflow_id="operation-child",
                retention_timestamp=1,
            )
        )
    async with workflow_store() as db, db.begin():
        result = await purge_workflow_history(db, before=datetime.now(UTC) - timedelta(days=7))
        assert result == {"workflow_history": 1, "datasource_checkpoints": 1}
        counts = await workflow_storage_counts(db)
        assert counts == {
            "workflow_history_count": 9,
            "workflow_checkpoint_count": 10,
            "datasource_checkpoint_count": 9,
        }
        for table in (SystemSchema.workflow_input, SystemSchema.workflow_output):
            assert set(await db.scalars(select(table.c.workflow_uuid))) == {
                "running",
                "queued",
                "delayed",
                "unknown",
                "unconfirmed-completion",
                "recent",
                "foreign",
                "native-child",
                "operation-child",
            }


@pytest.mark.anyio
async def test_expired_parent_is_retired_before_its_descendants(workflow_store):
    async with workflow_store() as db, db.begin():
        await _workflow(db, "parent")
        await _workflow(db, "child", parent="parent")
        await _workflow(db, "grandchild", parent="child")
    before = datetime.now(UTC) - timedelta(days=7)
    for expected in (1, 1, 1, 0):
        async with workflow_store() as db, db.begin():
            result = await purge_workflow_history(db, before=before)
            assert result["workflow_history"] == expected
    async with workflow_store() as db:
        assert await workflow_storage_counts(db) == {
            "workflow_history_count": 0,
            "workflow_checkpoint_count": 0,
            "datasource_checkpoint_count": 0,
        }
        for table in (SystemSchema.workflow_input, SystemSchema.workflow_output):
            assert await db.scalar(select(func.count()).select_from(table)) == 0


@pytest.mark.anyio
@pytest.mark.usefixtures("isolated_dbos_registry")
async def test_sdk_created_child_is_protected_until_its_parent_retires(async_session_factory):
    engine = async_session_factory.kw["bind"]
    queue = "tests.retention"

    @ads.transaction()
    async def child_checkpoint():
        return await ads.sql_session().scalar(select(42))

    @DBOS.workflow(name="tests.retention_child")
    async def child_workflow():
        return await child_checkpoint()

    @DBOS.workflow(name="tests.retention_parent")
    async def parent_workflow(child_id: str):
        return await enqueue_child_workflow(
            "tests.retention_child", queue_name=queue, workflow_id=child_id
        )

    DBOS(
        config=DBOSConfig(
            name="quirebase",
            application_version="retention-test",
            system_database_url=str(engine.url.set(drivername="sqlite")),
            enable_otlp=False,
        )
    )
    try:
        DBOS.launch()
        await DBOS.register_queue_async(queue, worker_concurrency=1, polling_interval_sec=0.05)
        child_id = str(uuid4())
        parent = await DBOS.start_workflow_async(parent_workflow, child_id)
        parent_id = parent.get_workflow_id()
        assert await asyncio.wait_for(parent.get_result(), timeout=10) == child_id
        child = await DBOS.retrieve_workflow_async(child_id)
        assert await asyncio.wait_for(child.get_result(), timeout=10) == 42

        status = SystemSchema.workflow_status
        operations = SystemSchema.operation_outputs
        before = datetime.now(UTC) - timedelta(days=7)
        expired = int((before - timedelta(days=1)).timestamp() * 1000)
        async with async_session_factory() as db, db.begin():
            connection = await db.connection()
            await connection.execution_options(schema_translate_map={SCHEMA_PLACEHOLDER: None})
            # These two recovery edges must come from the SDK, not test fixtures.
            assert (
                await db.scalar(
                    select(status.c.parent_workflow_id).where(status.c.workflow_uuid == child_id)
                )
                == parent_id
            )
            assert (
                await db.scalar(
                    select(operations.c.child_workflow_id).where(
                        operations.c.workflow_uuid == parent_id,
                        operations.c.child_workflow_id == child_id,
                    )
                )
                == child_id
            )
            await db.execute(
                update(status)
                .where(status.c.workflow_uuid == child_id)
                .values(completed_at=expired)
            )

        async with async_session_factory() as db, db.begin():
            assert await purge_workflow_history(db, before=before) == {
                "workflow_history": 0,
                "datasource_checkpoints": 0,
            }
            # DBOS 3 copies the committed result into operation_outputs, then
            # removes the completed workflow's datasource receipt.
            assert (await workflow_storage_counts(db))["datasource_checkpoint_count"] == 0
            await db.execute(
                update(status)
                .where(status.c.workflow_uuid == parent_id)
                .values(completed_at=expired)
            )

        async with async_session_factory() as db, db.begin():
            assert await purge_workflow_history(db, before=before) == {
                "workflow_history": 1,
                "datasource_checkpoints": 0,
            }
            assert await db.scalar(select(status.c.workflow_uuid)) == child_id
        child = await DBOS.retrieve_workflow_async(child_id)
        assert await child.get_result() == 42
        async with async_session_factory() as db, db.begin():
            assert await purge_workflow_history(db, before=before) == {
                "workflow_history": 1,
                "datasource_checkpoints": 0,
            }
            assert await workflow_storage_counts(db) == {
                "workflow_history_count": 0,
                "workflow_checkpoint_count": 0,
                "datasource_checkpoint_count": 0,
            }
    finally:
        await asyncio.to_thread(DBOS.destroy)


@pytest.mark.anyio
async def test_history_and_datasource_receipts_retire_atomically(workflow_store):
    async with workflow_store() as db, db.begin():
        await _workflow(db, "rollback")
    async with workflow_store() as db:
        await purge_workflow_history(db, before=datetime.now(UTC) - timedelta(days=7))
        await db.rollback()
        assert await workflow_storage_counts(db) == {
            "workflow_history_count": 1,
            "workflow_checkpoint_count": 1,
            "datasource_checkpoint_count": 1,
        }
        for table in (SystemSchema.workflow_input, SystemSchema.workflow_output):
            assert await db.scalar(select(table.c.workflow_uuid)) == "rollback"


@pytest.mark.anyio
@pytest.mark.parametrize("winner", ["resume", "retention"])
async def test_resume_and_retirement_preserve_the_winning_transaction(retention_race_store, winner):
    sessions, identity = retention_race_store
    engine = sessions.kw["bind"]
    schema = None if engine.dialect.name == "sqlite" else "dbos"
    status = SystemSchema.workflow_status
    receipts = _DATASOURCE_OUTPUTS
    async with sessions() as db, db.begin():
        await _workflow(db, identity, status="CANCELLED")
    attempted = asyncio.Event()

    def before_execute(_connection, _cursor, statement, _parameters, _context, _executemany):
        command = "DELETE" if winner == "resume" else "UPDATE"
        if statement.lstrip().startswith(command) and "workflow_status" in statement:
            attempted.set()

    async def resume(db):
        connection = await db.connection()
        await connection.execution_options(schema_translate_map={SCHEMA_PLACEHOLDER: schema})
        return await db.execute(
            update(status)
            .where(status.c.workflow_uuid == identity, status.c.status == "CANCELLED")
            .values(status="ENQUEUED", completed_at=None)
        )

    async def contender():
        async with sessions() as db, db.begin():
            if winner == "resume":
                return await purge_workflow_history(
                    db, before=datetime.now(UTC) - timedelta(days=7)
                )
            return (await resume(db)).rowcount

    task = None
    try:
        async with sessions() as winner_db, winner_db.begin():
            if winner == "resume":
                assert (await resume(winner_db)).rowcount == 1
            else:
                result = await purge_workflow_history(
                    winner_db, before=datetime.now(UTC) - timedelta(days=7)
                )
                assert result["workflow_history"] == 1
            event.listen(engine.sync_engine, "before_cursor_execute", before_execute)
            task = asyncio.create_task(contender())
            # Wait for the competing SQL to be sent while the winning write is
            # still uncommitted. SQLite waits; PG GC can SKIP LOCKED on resume.
            await asyncio.wait_for(attempted.wait(), timeout=5)
        result = await asyncio.wait_for(task, timeout=5)
        if winner == "resume":
            assert result["workflow_history"] == 0
        else:
            assert result == 0
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_execute)
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    async with sessions() as db:
        connection = await db.connection()
        await connection.execution_options(schema_translate_map={SCHEMA_PLACEHOLDER: schema})
        current = await db.scalar(select(status.c.status).where(status.c.workflow_uuid == identity))
        count = await db.scalar(
            select(func.count()).select_from(receipts).where(receipts.c.workflow_id == identity)
        )
        assert current == ("ENQUEUED" if winner == "resume" else None)
        assert count == (1 if winner == "resume" else 0)
        for table in (SystemSchema.workflow_input, SystemSchema.workflow_output):
            assert await db.scalar(
                select(func.count()).select_from(table).where(table.c.workflow_uuid == identity)
            ) == (1 if winner == "resume" else 0)


@pytest.mark.anyio
async def test_late_datasource_error_is_collected_on_later_round_without_expired_workflows(
    workflow_store,
):
    async with workflow_store() as db, db.begin():
        await _workflow(db, "cancelled", status="CANCELLED")
    async with workflow_store() as db, db.begin():
        await purge_workflow_history(db, before=datetime.now(UTC) - timedelta(days=7))
        assert await purge_orphan_datasource_outputs(db, before=datetime.now(UTC)) == 0
    # The SDK records datasource errors in an independent transaction, potentially
    # after an entire GC round has finished. This must not become permanent.
    async with workflow_store() as db, db.begin():
        await db.execute(
            _DATASOURCE_OUTPUTS
            .insert()
            .values(
                workflow_id="cancelled",
                step_id=9,
                error="late error",
                created_at=int(datetime.now(UTC).timestamp() * 1000),
            )
            .execution_options(schema_translate_map={SCHEMA_PLACEHOLDER: None})
        )
    async with workflow_store() as db, db.begin():
        assert (await purge_workflow_history(db, before=datetime.now(UTC) - timedelta(days=7)))[
            "workflow_history"
        ] == 0
        assert await purge_orphan_datasource_outputs(db, before=datetime.now(UTC)) == 1
        assert (await workflow_storage_counts(db))["datasource_checkpoint_count"] == 0


@pytest.mark.anyio
async def test_orphan_sweep_is_bounded_and_keeps_live_receipts(workflow_store):
    async with workflow_store() as db, db.begin():
        await _workflow(db, "live", status="PENDING")
        for index in range(3):
            await db.execute(
                _DATASOURCE_OUTPUTS.insert().values(
                    workflow_id=f"orphan-{index}", step_id=1, created_at=1
                )
            )
        assert await purge_orphan_datasource_outputs(db, before=datetime.now(UTC), limit=2) == 2
        assert await purge_orphan_datasource_outputs(db, before=datetime.now(UTC), limit=2) == 1
        assert await purge_orphan_datasource_outputs(db, before=datetime.now(UTC), limit=2) == 0
        assert (await workflow_storage_counts(db))["datasource_checkpoint_count"] == 1


@pytest.mark.anyio
async def test_scan_snapshot_is_single_bounded_and_rejects_older_completion(async_db):
    started = datetime.now(UTC)
    errors = [f"revision-{index}: missing object" for index in range(123)]
    await maintenance.record_integrity_scan(async_db, started, errors, {})
    await async_db.commit()
    await maintenance.record_integrity_scan(async_db, started - timedelta(hours=1), [], {})
    await async_db.commit()
    assert await async_db.scalar(select(func.count()).select_from(MaintenanceSnapshot)) == 1
    snapshot = await async_db.get(MaintenanceSnapshot, 1)
    assert snapshot.error_count == 123
    assert snapshot.missing_count == 123
    assert snapshot.errors == errors[:100]
    assert snapshot.status == "inconsistencies_found"

    await maintenance.record_integrity_scan(async_db, started + timedelta(seconds=1), [], {})
    await async_db.commit()
    async_db.expire_all()
    snapshot = await async_db.get(MaintenanceSnapshot, 1)
    assert snapshot.status == "ok"
    assert snapshot.errors == []
    assert snapshot.error_count == 0
    assert await async_db.scalar(select(func.count()).select_from(MaintenanceSnapshot)) == 1


@pytest.mark.anyio
async def test_maintenance_snapshot_database_enforces_singleton(async_db):
    started = datetime.now(UTC)
    await maintenance.record_integrity_scan(async_db, started, [], {})
    await async_db.commit()

    async with async_db.begin_nested() as savepoint:
        async_db.add(MaintenanceSnapshot(id=2))
        with pytest.raises(IntegrityError):
            await async_db.flush()
        await savepoint.rollback()

    snapshot = await async_db.get(MaintenanceSnapshot, 1)
    assert snapshot.status == "ok"
    assert await async_db.scalar(select(func.count()).select_from(MaintenanceSnapshot)) == 1


@pytest.mark.anyio
async def test_cleanup_snapshot_preserves_scan_and_rejects_stale_success(
    async_db, async_session_factory, monkeypatch
):
    monkeypatch.setattr(maintenance, "AsyncSessionLocal", async_session_factory)
    started = datetime.now(UTC)
    await maintenance.record_integrity_scan(async_db, started, [], {})
    await async_db.commit()
    await maintenance._save_cleanup_snapshot(started, counts={"audit_events": 3})
    await maintenance._save_cleanup_snapshot(started - timedelta(hours=1), error="OldFailure")
    async_db.expire_all()
    snapshot = await async_db.get(MaintenanceSnapshot, 1)
    assert snapshot.status == "ok"
    assert snapshot.cleanup_counts == {"audit_events": 3}
    assert snapshot.cleanup_checked_at is not None
    assert snapshot.cleanup_error is None
    await async_db.rollback()
    await maintenance._save_cleanup_snapshot(started + timedelta(seconds=1), error="DatabaseError")
    async_db.expire_all()
    snapshot = await async_db.get(MaintenanceSnapshot, 1)
    assert snapshot.cleanup_checked_at is None
    assert snapshot.cleanup_counts is None
    assert snapshot.cleanup_error == "DatabaseError"


@pytest.mark.anyio
async def test_retention_batches_continue_through_small_parent_batches(
    async_session_factory, monkeypatch
):
    monkeypatch.setattr(maintenance, "AsyncSessionLocal", async_session_factory)
    calls = 0

    async def purge(db, *, limit):
        nonlocal calls
        await db.flush()
        calls += 1
        return {"workflow_history": 1 if calls <= 3 else 0}

    assert await maintenance._purge_retention_batches(purge) == {"workflow_history": 3}
    assert calls == 4


@pytest.mark.anyio
async def test_import_cleanup_continues_after_a_protected_page(async_session_factory, monkeypatch):
    from quirebase import library

    monkeypatch.setattr(maintenance, "AsyncSessionLocal", async_session_factory)
    first, second = uuid4(), uuid4()
    observed = []

    async def purge(db, *, before, limit, after):
        await db.flush()
        observed.append(after)
        return {None: (0, first), first: (1, second), second: (0, None)}[after]

    monkeypatch.setattr(library, "purge_expired_import_batches", purge)
    assert await maintenance._purge_import_batches(datetime.now(UTC)) == 1
    assert observed == [None, first, second]


@pytest.mark.anyio
async def test_hourly_cleanup_retires_its_own_history_and_publishes_latest_counts(
    workflow_store, monkeypatch
):
    monkeypatch.setattr(maintenance, "AsyncSessionLocal", workflow_store)
    for round_number in range(3):
        async with workflow_store() as db, db.begin():
            await _workflow(db, f"old-maintenance-{round_number}")
            await _workflow(
                db,
                f"old-maintenance-child-{round_number}",
                parent=f"old-maintenance-{round_number}",
            )
        result = await maintenance.cleanup_retained_data_step()
        assert result["workflow_history"] == 2
        assert result["datasource_checkpoints"] == 2
        assert result["orphan_datasource_checkpoints"] == 0
        async with workflow_store() as db:
            assert (await workflow_storage_counts(db))["workflow_history_count"] == 0
            snapshot = await db.get(MaintenanceSnapshot, 1)
            assert snapshot.status == "not_checked"
            assert snapshot.checked_at is None
            assert snapshot.cleanup_checked_at is not None
            assert snapshot.cleanup_counts == result
            assert await db.scalar(select(func.count()).select_from(MaintenanceSnapshot)) == 1


@pytest.mark.anyio
async def test_failed_retention_is_not_published_as_success(workflow_store, monkeypatch):
    monkeypatch.setattr(maintenance, "AsyncSessionLocal", workflow_store)

    async def fail(db, **kwargs):
        await db.flush()
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(maintenance, "purge_workflow_history", fail)
    with pytest.raises(RuntimeError, match="database unavailable"):
        await maintenance.cleanup_retained_data_step()
    async with workflow_store() as db:
        snapshot = await db.get(MaintenanceSnapshot, 1)
        assert snapshot.cleanup_checked_at is None
        assert snapshot.cleanup_counts is None
        assert snapshot.cleanup_error == "RuntimeError"


@pytest.mark.anyio
async def test_failed_integrity_io_clears_success_timestamp(async_session_factory, monkeypatch):
    monkeypatch.setattr(maintenance, "AsyncSessionLocal", async_session_factory)
    async with async_session_factory() as db, db.begin():
        await maintenance.record_integrity_scan(db, datetime.now(UTC) - timedelta(hours=1), [], {})

    async def fail(db):
        await db.flush()
        raise OSError("private endpoint detail")

    monkeypatch.setattr(maintenance, "scan_objects", fail)
    with pytest.raises(OSError):
        await maintenance.scan_objects_step()
    async with async_session_factory() as db:
        snapshot = await db.get(MaintenanceSnapshot, 1)
        assert snapshot.status == "failed"
        assert snapshot.checked_at is None
        assert snapshot.errors == ["OSError"]
