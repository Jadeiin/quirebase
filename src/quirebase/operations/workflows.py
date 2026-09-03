from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from dbos import DBOS

from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.database import AsyncSessionLocal
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.core.workflows import OPERATIONS_QUEUE, ads, durable_operations
from quirebase.models import ObjectIntegrityScan
from quirebase.search import reindex_all

from .maintenance import (
    cleanup_exports,
    create_backup,
    delete_orphan_candidates,
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


@ads.transaction()
async def reindex_all_step() -> dict[str, Any]:
    db = ads.sql_session()
    count = await reindex_all(db)
    return {"reindexed_items": count}


@DBOS.workflow(name=REINDEX_WORKFLOW)
async def reindex_all_workflow(_workflow_id: str, _owner_id: str) -> dict[str, Any]:
    return await reindex_all_step()


@DBOS.step(retries_allowed=True, max_attempts=3)
async def scan_objects_step() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        errors, candidates = await scan_objects(db)
        await db.commit()
        return {"errors": errors, "orphan_candidates": list(candidates)}


@DBOS.step(retries_allowed=True, max_attempts=3)
async def delete_orphan_candidates_step(candidates: list[str]) -> list[str]:
    async with AsyncSessionLocal() as db:
        deleted = await delete_orphan_candidates(db, tuple(candidates))
        return list(deleted)


@ads.transaction()
async def record_integrity_scan_step(errors: list[str]) -> None:
    db = ads.sql_session()
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
    await record_integrity_scan_step(errors)
    return {
        "errors": errors,
        "deleted_orphans": deleted,
        "checked_status": "ok" if not errors else "inconsistencies_found",
    }


@DBOS.workflow(name=CHECK_OBJECTS_WORKFLOW)
async def check_objects_workflow(_workflow_id: str, _owner_id: str) -> dict[str, Any]:
    return await _run_integrity_scan()


@DBOS.step(retries_allowed=True, max_attempts=3)
async def cleanup_exports_step() -> int:
    async with AsyncSessionLocal() as db:
        return await cleanup_exports(db)


@DBOS.workflow(name=PERIODIC_MAINTENANCE_WORKFLOW)
async def periodic_maintenance_workflow(_scheduled_time: Any, _context: Any) -> None:
    await cleanup_exports_step()
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


@ads.transaction()
async def list_items_for_tag_recommendation_step() -> tuple[str, ...]:
    from quirebase.library import item_ids_for_tag_recommendation

    db = ads.sql_session()
    return await item_ids_for_tag_recommendation(db)


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
    item_ids = await list_items_for_tag_recommendation_step()
    enqueued = 0
    for item_id in item_ids:
        enqueued += await request_item_tag_recommendation_step(item_id, owner_id)
    return {"enqueued_items": enqueued}
