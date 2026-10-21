from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from advanced_alchemy.types import FileObject
from dbos import DBOS
from sqlalchemy import or_, select, update

from quirebase.access import (
    ResourceAction,
    SystemAction,
    require_system_action,
    require_workspace_action,
)
from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.database import AsyncSessionLocal
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.core.persistence import conflict_insert
from quirebase.core.workflow_storage import (
    purge_orphan_datasource_outputs,
    purge_workflow_history,
)
from quirebase.core.workflows import OPERATIONS_QUEUE, ads, durable_operations
from quirebase.documents import (
    delete_unreferenced_objects,
    list_expired_export_artifacts,
    retire_expired_export_artifacts,
)
from quirebase.models import FileRevision, Item, MaintenanceSnapshot, User
from quirebase.search import search_index

from .maintenance import (
    cleanup_local_exports,
    delete_orphan_candidates,
    scan_objects,
)

if TYPE_CHECKING:
    from dbos import ScheduleInput

REINDEX_WORKFLOW = "operations.reindex_workspace"
CHECK_OBJECTS_WORKFLOW = "operations.check_objects"
PERIODIC_MAINTENANCE_WORKFLOW = "operations.periodic_maintenance"
PERIODIC_MAINTENANCE_SCHEDULE = "operations.periodic_maintenance.hourly"

_MAINTENANCE_WORKFLOWS = {
    "check_objects": CHECK_OBJECTS_WORKFLOW,
}

_REINDEX_BATCH_SIZE = 100
_EXPORT_CLEANUP_BATCH_SIZE = 100
_RETENTION_BATCH_SIZE = 500
_RETENTION_MAX_BATCHES = 100
_INTEGRITY_ERROR_SAMPLE_SIZE = 100


async def dispatch_maintenance_workflow(db, admin: User, operation: str) -> str:
    admin = await require_system_action(db, admin, SystemAction.maintenance_run, lock="shared")
    workflow_name = _MAINTENANCE_WORKFLOWS.get(operation)
    if workflow_name is None:
        raise ValidationFailure(f"unknown maintenance operation: {operation}")
    workflow_id = f"maintenance:{operation}:{uuid4()}"
    record_event(db, admin.id, f"admin.maintenance.{operation}", "workflow", workflow_id)
    await db.flush()
    await durable_operations().enqueue_in_transaction(
        db,
        workflow_name,
        workflow_id,
        admin.id,
        None,
        queue_name=OPERATIONS_QUEUE,
        workflow_id=workflow_id,
        attributes={
            "capability": "operations",
            "operation": operation,
            "actor_id": admin.id,
            "workspace_id": None,
        },
    )
    await db.commit()
    return workflow_id


async def dispatch_workspace_reindex(db, actor: User, workspace_id: UUID) -> str:
    context = await require_workspace_action(
        db, actor, workspace_id, ResourceAction.workspace_maintenance_run
    )
    workflow_id = f"maintenance:reindex:{workspace_id}:{uuid4()}"
    record_event(
        db,
        actor.id,
        "workspace.maintenance.reindex",
        "workflow",
        workflow_id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.workspace_maintenance_run.value,
    )
    await db.flush()
    await durable_operations().enqueue_in_transaction(
        db,
        REINDEX_WORKFLOW,
        workflow_id,
        actor.id,
        workspace_id,
        queue_name=OPERATIONS_QUEUE,
        workflow_id=workflow_id,
        attributes={
            "capability": "operations",
            "operation": "reindex",
            "actor_id": actor.id,
            "workspace_id": workspace_id,
        },
    )
    await db.commit()
    return workflow_id


@ads.transaction(isolation_level="READ COMMITTED")
async def list_reindex_item_ids_step(
    actor_id: UUID, workspace_id: UUID, after_id: UUID | None, limit: int
) -> tuple[UUID, ...]:
    db = ads.sql_session()
    actor = await db.get(User, actor_id)
    if actor is None:
        raise ResourceUnavailable("reindex actor is unavailable")
    await require_workspace_action(
        db, actor, workspace_id, ResourceAction.workspace_maintenance_run
    )
    query = select(Item.id).where(Item.workspace_id == workspace_id).order_by(Item.id).limit(limit)
    if after_id is not None:
        query = query.where(Item.id > after_id)
    return tuple((await db.scalars(query)).all())


@ads.transaction()
async def reindex_items_step(actor_id: UUID, workspace_id: UUID, item_ids: tuple[UUID, ...]) -> int:
    db = ads.sql_session()
    actor = await db.get(User, actor_id)
    if actor is None:
        raise ResourceUnavailable("reindex actor is unavailable")
    await require_workspace_action(
        db, actor, workspace_id, ResourceAction.workspace_maintenance_run
    )
    visible_ids = set(
        (
            await db.scalars(
                select(Item.id).where(
                    Item.workspace_id == workspace_id,
                    Item.id.in_(item_ids),
                )
            )
        ).all()
    )
    index = search_index(db)
    for item_id in item_ids:
        if item_id in visible_ids:
            await index.index_item(db, item_id)
    return len(visible_ids)


@ads.transaction(isolation_level="READ COMMITTED")
async def list_reindex_revision_ids_step(
    actor_id: UUID, workspace_id: UUID, after_id: UUID | None, limit: int
) -> tuple[UUID, ...]:
    db = ads.sql_session()
    actor = await db.get(User, actor_id)
    if actor is None:
        raise ResourceUnavailable("reindex actor is unavailable")
    await require_workspace_action(
        db, actor, workspace_id, ResourceAction.workspace_maintenance_run
    )
    query = (
        select(FileRevision.id)
        .where(FileRevision.workspace_id == workspace_id)
        .order_by(FileRevision.id)
        .limit(limit)
    )
    if after_id is not None:
        query = query.where(FileRevision.id > after_id)
    return tuple((await db.scalars(query)).all())


@ads.transaction()
async def reindex_revisions_step(
    actor_id: UUID, workspace_id: UUID, revision_ids: tuple[UUID, ...]
) -> int:
    db = ads.sql_session()
    actor = await db.get(User, actor_id)
    if actor is None:
        raise ResourceUnavailable("reindex actor is unavailable")
    await require_workspace_action(
        db, actor, workspace_id, ResourceAction.workspace_maintenance_run
    )
    visible_ids = set(
        (
            await db.scalars(
                select(FileRevision.id).where(
                    FileRevision.workspace_id == workspace_id,
                    FileRevision.id.in_(revision_ids),
                )
            )
        ).all()
    )
    index = search_index(db)
    for revision_id in revision_ids:
        if revision_id in visible_ids:
            await index.index_revision(db, revision_id)
    return len(visible_ids)


@DBOS.workflow(name=REINDEX_WORKFLOW)
async def reindex_workspace_workflow(
    _workflow_id: str, actor_id: UUID, workspace_id: UUID
) -> dict[str, Any]:
    total = 0
    after_id: UUID | None = None
    while True:
        item_ids = await list_reindex_item_ids_step(
            actor_id, workspace_id, after_id, _REINDEX_BATCH_SIZE
        )
        if not item_ids:
            break
        total += await reindex_items_step(actor_id, workspace_id, item_ids)
        if len(item_ids) < _REINDEX_BATCH_SIZE:
            break
        after_id = item_ids[-1]
    revision_total = 0
    after_revision_id: UUID | None = None
    while True:
        revision_ids = await list_reindex_revision_ids_step(
            actor_id, workspace_id, after_revision_id, _REINDEX_BATCH_SIZE
        )
        if not revision_ids:
            break
        revision_total += await reindex_revisions_step(actor_id, workspace_id, revision_ids)
        if len(revision_ids) < _REINDEX_BATCH_SIZE:
            break
        after_revision_id = revision_ids[-1]
    return {"reindexed_items": total, "reindexed_revisions": revision_total}


@DBOS.step(retries_allowed=True, max_attempts=3)
async def scan_objects_step() -> dict[str, Any]:
    started_at = datetime.now(UTC)
    try:
        async with AsyncSessionLocal() as db:
            errors, candidates, thumbnail_sizes = await scan_objects(db)
            deleted = await delete_orphan_candidates(db, candidates)
            await db.rollback()
            async with db.begin():
                await record_integrity_scan(db, started_at, errors, thumbnail_sizes)
        return {
            "error_count": len(errors),
            "deleted_orphans": len(deleted),
            "checked_status": "ok" if not errors else "inconsistencies_found",
        }
    except Exception as exc:
        async with AsyncSessionLocal() as db, db.begin():
            await _save_integrity_snapshot(
                db,
                started_at,
                status="failed",
                checked_at=None,
                errors=[type(exc).__name__],
                error_count=1,
                missing_count=0,
                mismatch_count=0,
            )
        raise


async def _save_integrity_snapshot(db, started_at: datetime, **values: Any) -> None:
    statement = conflict_insert(db, MaintenanceSnapshot).values(
        id=1, started_at=started_at, **values
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[MaintenanceSnapshot.id],
            set_={"started_at": started_at, **values},
            where=or_(
                MaintenanceSnapshot.started_at.is_(None),
                MaintenanceSnapshot.started_at <= started_at,
            ),
        )
    )


async def record_integrity_scan(
    db, started_at: datetime, errors: list[str], thumbnail_sizes: dict[str, dict]
) -> None:
    for revision_id, repair in thumbnail_sizes.items():
        revision = await db.scalar(
            select(FileRevision).where(FileRevision.id == UUID(revision_id)).with_for_update()
        )
        if (
            revision is not None
            and revision.thumbnail is not None
            and revision.thumbnail.path == repair["path"]
            and revision.thumbnail.size is None
        ):
            # FileObject equality ignores metadata at an unchanged path. Always emit SQL.
            descriptor = FileObject(**(revision.thumbnail.to_dict() | {"size": repair["size"]}))
            await db.execute(
                update(FileRevision)
                .where(FileRevision.id == revision.id)
                .values(thumbnail=descriptor)
            )
    missing_count = sum("missing " in error for error in errors)
    mismatch_count = sum("mismatch" in error for error in errors)
    await _save_integrity_snapshot(
        db,
        started_at,
        status="ok" if not errors else "inconsistencies_found",
        missing_count=missing_count,
        mismatch_count=mismatch_count,
        error_count=len(errors),
        errors=errors[:_INTEGRITY_ERROR_SAMPLE_SIZE],
        checked_at=datetime.now(UTC),
    )


async def _run_integrity_scan() -> dict[str, Any]:
    return await scan_objects_step()


@DBOS.workflow(name=CHECK_OBJECTS_WORKFLOW)
async def check_objects_workflow(
    _workflow_id: str, _actor_id: UUID, _workspace_id: None
) -> dict[str, Any]:
    return await _run_integrity_scan()


@DBOS.step(retries_allowed=True, max_attempts=3)
async def cleanup_exports_step(ttl_hours: int) -> int:
    return await cleanup_local_exports(ttl_hours)


@ads.transaction(isolation_level="READ COMMITTED")
async def get_export_ttl_step() -> int:
    from quirebase.operations.settings import get_effective_setting

    return await get_effective_setting(
        ads.sql_session(), "export_ttl_hours", get_settings().export_ttl_hours
    )


@ads.transaction(isolation_level="READ COMMITTED")
async def list_expired_export_artifacts_step(
    limit: int,
) -> tuple[dict[str, str], ...]:
    return await list_expired_export_artifacts(ads.sql_session(), limit)


@ads.transaction(isolation_level="READ COMMITTED")
async def retire_expired_export_artifacts_step(
    artifacts: tuple[dict[str, str], ...],
) -> tuple[str, ...]:
    return await retire_expired_export_artifacts(ads.sql_session(), artifacts)


@DBOS.step(retries_allowed=True, max_attempts=3)
async def delete_export_artifact_objects_step(keys: tuple[str, ...]) -> int:
    async with AsyncSessionLocal() as db:
        return len(await delete_unreferenced_objects(db, keys))


async def _run_export_cleanup() -> int:
    removed = await cleanup_exports_step(await get_export_ttl_step())
    while True:
        artifacts = await list_expired_export_artifacts_step(_EXPORT_CLEANUP_BATCH_SIZE)
        if not artifacts:
            break
        keys = await retire_expired_export_artifacts_step(artifacts)
        removed += await delete_export_artifact_objects_step(keys)
    return removed


async def _purge_retention_batches(
    purge, *, key: str | None = None, **parameters
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _ in range(_RETENTION_MAX_BATCHES):
        async with AsyncSessionLocal() as db, db.begin():
            batch = await purge(db, limit=_RETENTION_BATCH_SIZE, **parameters)
        if isinstance(batch, int):
            assert key is not None
            batch = {key: batch}
        for name, count in batch.items():
            counts[name] = counts.get(name, 0) + count
        # Retiring a parent makes its children newly eligible, even if the parent
        # batch was smaller than the page limit. Continue until an empty batch.
        if not any(batch.values()):
            break
    return counts


async def _purge_import_batches(before: datetime) -> int:
    from quirebase.library import purge_expired_import_batches

    removed = 0
    after = None
    for _ in range(_RETENTION_MAX_BATCHES):
        async with AsyncSessionLocal() as db, db.begin():
            count, after = await purge_expired_import_batches(
                db, before=before, limit=_RETENTION_BATCH_SIZE, after=after
            )
        removed += count
        if after is None:
            break
    return removed


async def _save_cleanup_snapshot(
    started_at: datetime, *, counts: dict[str, int] | None = None, error: str | None = None
) -> None:
    values = {
        "cleanup_started_at": started_at,
        "cleanup_checked_at": datetime.now(UTC) if counts is not None else None,
        "cleanup_counts": counts,
        "cleanup_error": error,
    }
    async with AsyncSessionLocal() as db, db.begin():
        statement = conflict_insert(db, MaintenanceSnapshot).values(id=1, **values)
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[MaintenanceSnapshot.id],
                set_=values,
                where=or_(
                    MaintenanceSnapshot.cleanup_started_at.is_(None),
                    MaintenanceSnapshot.cleanup_started_at <= started_at,
                ),
            )
        )


@DBOS.step(retries_allowed=True, max_attempts=3)
async def cleanup_retained_data_step() -> dict[str, int]:
    # Import the owned maintenance operations at execution time: Accounts and
    # Workspaces also consume Operations runtime settings during facade bootstrap.
    from quirebase.accounts import purge_expired_account_records
    from quirebase.audit import purge_audit_events
    from quirebase.documents import purge_deleted_annotations, purge_deleted_replies
    from quirebase.workspaces import purge_workspace_history

    settings = get_settings()
    started_at = datetime.now(UTC)
    terminal_before = started_at - timedelta(days=settings.terminal_metadata_retention_days)
    annotation_before = started_at - timedelta(hours=settings.annotation_undo_hours)
    await _save_cleanup_snapshot(started_at)
    try:
        counts = await _purge_retention_batches(
            purge_expired_account_records, now=started_at, terminal_before=terminal_before
        )
        counts.update(
            await _purge_retention_batches(purge_workspace_history, before=terminal_before)
        )
        counts.update(
            await _purge_retention_batches(
                purge_audit_events,
                key="audit_events",
                before=started_at - timedelta(days=settings.audit_retention_days),
            )
        )
        counts.update(
            await _purge_retention_batches(
                purge_deleted_replies, key="annotation_replies", before=annotation_before
            )
        )
        counts.update(
            await _purge_retention_batches(
                purge_deleted_annotations, key="annotations", before=annotation_before
            )
        )
        counts["import_batches"] = await _purge_import_batches(
            started_at - timedelta(days=settings.import_batch_retention_days)
        )
        counts.update(
            await _purge_retention_batches(
                purge_workflow_history,
                before=started_at - timedelta(days=settings.workflow_history_retention_days),
            )
        )
        # Always sweep, even when no workflow expired this round. Late SDK result
        # and independent error receipts can arrive after an earlier retirement.
        counts["orphan_datasource_checkpoints"] = (
            await _purge_retention_batches(
                purge_orphan_datasource_outputs,
                key="orphan_datasource_checkpoints",
                before=started_at,
            )
        )["orphan_datasource_checkpoints"]
    except Exception as exc:
        await _save_cleanup_snapshot(started_at, error=type(exc).__name__)
        raise
    await _save_cleanup_snapshot(started_at, counts=counts)
    return counts


@DBOS.workflow(name=PERIODIC_MAINTENANCE_WORKFLOW)
async def periodic_maintenance_workflow(_scheduled_time: Any, _context: Any) -> None:
    # Database retention remains available when Object Store maintenance fails.
    await cleanup_retained_data_step()
    await _run_export_cleanup()
    await _run_integrity_scan()


def maintenance_schedules() -> list[ScheduleInput]:
    return [
        {
            "schedule_name": PERIODIC_MAINTENANCE_SCHEDULE,
            "workflow_fn": periodic_maintenance_workflow,
            "schedule": "0 * * * *",
            "context": None,
            "automatic_backfill": False,
            "queue_name": OPERATIONS_QUEUE,
        }
    ]
