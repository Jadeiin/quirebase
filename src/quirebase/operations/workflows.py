from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from dbos import DBOS
from sqlalchemy import select, update

from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.database import AsyncSessionLocal
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.core.workflows import OPERATIONS_QUEUE, ads, durable_operations
from quirebase.models import FileRevision, Item, ObjectIntegrityScan
from quirebase.search import search_index

from .maintenance import (
    cleanup_local_exports,
    create_backup,
    delete_export_artifact_objects,
    delete_export_artifact_records,
    delete_orphan_candidates,
    list_expired_export_artifacts,
    scan_objects,
)

if TYPE_CHECKING:
    from dbos import ScheduleInput

    from quirebase.models import User

REINDEX_WORKFLOW = "operations.reindex_all"
CHECK_OBJECTS_WORKFLOW = "operations.check_objects"
BACKUP_WORKFLOW = "operations.backup"
RECOMMEND_TAGS_WORKFLOW = "operations.recommend_tags_all"
PERIODIC_MAINTENANCE_WORKFLOW = "operations.periodic_maintenance"
PERIODIC_MAINTENANCE_SCHEDULE = "operations.periodic_maintenance.hourly"

_MAINTENANCE_WORKFLOWS = {
    "reindex_all": REINDEX_WORKFLOW,
    "check_objects": CHECK_OBJECTS_WORKFLOW,
    "backup": BACKUP_WORKFLOW,
    "recommend_tags_all": RECOMMEND_TAGS_WORKFLOW,
}

_REINDEX_BATCH_SIZE = 100
_RECOMMEND_BATCH_SIZE = 100
_EXPORT_CLEANUP_BATCH_SIZE = 100


async def dispatch_maintenance_workflow(db, admin: User, operation: str) -> str:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
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
        queue_name=OPERATIONS_QUEUE,
        workflow_id=workflow_id,
        attributes={"capability": "operations", "operation": operation, "owner_id": admin.id},
    )
    await db.commit()
    return workflow_id


@ads.transaction(isolation_level="READ COMMITTED")
async def list_reindex_item_ids_step(after_id: str | None, limit: int) -> tuple[str, ...]:
    db = ads.sql_session()
    query = select(Item.id).order_by(Item.id).limit(limit)
    if after_id is not None:
        query = query.where(Item.id > after_id)
    return tuple((await db.scalars(query)).all())


@ads.transaction()
async def reindex_items_step(item_ids: tuple[str, ...]) -> int:
    db = ads.sql_session()
    index = search_index(db)
    for item_id in item_ids:
        await index.index_item(db, item_id)
    return len(item_ids)


@DBOS.workflow(name=REINDEX_WORKFLOW)
async def reindex_all_workflow(_workflow_id: str, _owner_id: str) -> dict[str, Any]:
    total = 0
    after_id: str | None = None
    while True:
        item_ids = await list_reindex_item_ids_step(after_id, _REINDEX_BATCH_SIZE)
        if not item_ids:
            break
        total += await reindex_items_step(item_ids)
        if len(item_ids) < _REINDEX_BATCH_SIZE:
            break
        after_id = item_ids[-1]
    return {"reindexed_items": total}


@DBOS.step(retries_allowed=True, max_attempts=3)
async def scan_objects_step() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        errors, candidates, thumbnail_sizes = await scan_objects(db)
        return {
            "errors": errors,
            "orphan_candidates": list(candidates),
            "thumbnail_sizes": thumbnail_sizes,
        }


@DBOS.step(retries_allowed=True, max_attempts=3)
async def delete_orphan_candidates_step(candidates: list[str]) -> list[str]:
    async with AsyncSessionLocal() as db:
        deleted = await delete_orphan_candidates(db, tuple(candidates))
        return list(deleted)


@ads.transaction(isolation_level="READ COMMITTED")
async def record_integrity_scan_step(errors: list[str], thumbnail_sizes: dict[str, int]) -> None:
    db = ads.sql_session()
    for revision_id, thumbnail_size in thumbnail_sizes.items():
        await db.execute(
            update(FileRevision)
            .where(
                FileRevision.id == revision_id,
                FileRevision.thumbnail_size.is_(None),
            )
            .values(thumbnail_size=thumbnail_size)
        )
    missing_count = sum("missing " in error for error in errors)
    mismatch_count = sum("mismatch" in error for error in errors)
    scan = await db.get(ObjectIntegrityScan, "latest")
    if scan is None:
        scan = ObjectIntegrityScan(
            id="latest",
            status="ok" if not errors else "inconsistencies_found",
            missing_count=missing_count,
            mismatch_count=mismatch_count,
            errors=json.dumps(errors, ensure_ascii=False),
        )
        db.add(scan)
    else:
        scan.status = "ok" if not errors else "inconsistencies_found"
        scan.missing_count = missing_count
        scan.mismatch_count = mismatch_count
        scan.errors = json.dumps(errors, ensure_ascii=False)
        scan.checked_at = datetime.now(UTC)
    await db.flush()


async def _run_integrity_scan() -> dict[str, Any]:
    report = await scan_objects_step()
    errors = report["errors"]
    deleted = await delete_orphan_candidates_step(report["orphan_candidates"])
    await record_integrity_scan_step(errors, report["thumbnail_sizes"])
    return {
        "errors": errors,
        "deleted_orphans": deleted,
        "checked_status": "ok" if not errors else "inconsistencies_found",
    }


@DBOS.workflow(name=CHECK_OBJECTS_WORKFLOW)
async def check_objects_workflow(_workflow_id: str, _owner_id: str) -> dict[str, Any]:
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


@DBOS.step(retries_allowed=True, max_attempts=3)
async def delete_export_artifact_objects_step(
    artifacts: tuple[dict[str, str], ...],
) -> dict[str, Any]:
    return await delete_export_artifact_objects(artifacts)


@ads.transaction(isolation_level="READ COMMITTED")
async def delete_export_artifact_records_step(workflow_ids: list[str]) -> int:
    return await delete_export_artifact_records(ads.sql_session(), workflow_ids)


async def _run_export_cleanup() -> int:
    removed = await cleanup_exports_step(await get_export_ttl_step())
    while True:
        artifacts = await list_expired_export_artifacts_step(_EXPORT_CLEANUP_BATCH_SIZE)
        if not artifacts:
            break
        result = await delete_export_artifact_objects_step(artifacts)
        await delete_export_artifact_records_step(result["workflow_ids"])
        removed += result["removed"]
    return removed


@DBOS.workflow(name=PERIODIC_MAINTENANCE_WORKFLOW)
async def periodic_maintenance_workflow(_scheduled_time: Any, _context: Any) -> None:
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


@DBOS.step(retries_allowed=True, max_attempts=3)
async def backup_step(workflow_id: str) -> dict[str, Any]:
    safe_id = "".join(
        character if character.isalnum() or character in "._-" else "_" for character in workflow_id
    )
    filename = f"backup_{safe_id}.zip"
    destination = get_settings().export_dir / filename
    await create_backup(destination)
    size = await asyncio.to_thread(lambda: destination.stat().st_size)
    return {"filename": filename, "size_bytes": size}


@DBOS.workflow(name=BACKUP_WORKFLOW)
async def backup_workflow(workflow_id: str, _owner_id: str) -> dict[str, Any]:
    return await backup_step(workflow_id)


@ads.transaction(isolation_level="READ COMMITTED")
async def list_items_for_tag_recommendation_step(
    after_id: str | None, limit: int
) -> tuple[str, ...]:
    from quirebase.library import item_ids_for_tag_recommendation

    db = ads.sql_session()
    return await item_ids_for_tag_recommendation(db, after_id, limit)


@ads.transaction()
async def request_item_tag_recommendation_step(item_id: str, owner_id: str) -> bool:
    from quirebase.library import request_item_tag_recommendation

    db = ads.sql_session()
    try:
        await request_item_tag_recommendation(db, item_id, owner_id=owner_id, force=True)
    except ValueError:
        return False
    return True


@DBOS.workflow(name=RECOMMEND_TAGS_WORKFLOW)
async def recommend_tags_all_workflow(_workflow_id: str, owner_id: str) -> dict[str, Any]:
    enqueued = 0
    after_id: str | None = None
    while True:
        item_ids = await list_items_for_tag_recommendation_step(after_id, _RECOMMEND_BATCH_SIZE)
        if not item_ids:
            break
        for item_id in item_ids:
            enqueued += await request_item_tag_recommendation_step(item_id, owner_id)
        if len(item_ids) < _RECOMMEND_BATCH_SIZE:
            break
        after_id = item_ids[-1]
    return {"enqueued_items": enqueued}
