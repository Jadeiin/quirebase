from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from dbos import DBOS

from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.database import AsyncSessionLocal
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.core.workflows import OPERATIONS_QUEUE, durable_operations
from quirebase.search import reindex_all

from .maintenance import check_objects, create_backup, reconcile_objects

if TYPE_CHECKING:
    from quirebase.models import User

REINDEX_WORKFLOW = "operations.reindex_all"
CHECK_OBJECTS_WORKFLOW = "operations.check_objects"
BACKUP_WORKFLOW = "operations.backup"
RECOMMEND_TAGS_WORKFLOW = "operations.recommend_tags_all"

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


@DBOS.step(retries_allowed=True, max_attempts=3)
async def reindex_all_step() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        count = await reindex_all(db)
        await db.commit()
        return {"reindexed_items": count}


@DBOS.workflow(name=REINDEX_WORKFLOW)
async def reindex_all_workflow(_workflow_id: str, _owner_id: str) -> dict[str, Any]:
    return await reindex_all_step()


@DBOS.step(retries_allowed=True, max_attempts=3)
async def check_objects_step() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        errors = await check_objects(db)
        deleted = await reconcile_objects(db)
        return {
            "errors": errors,
            "deleted_orphans": list(deleted),
            "checked_status": "ok" if not errors else "inconsistencies_found",
        }


@DBOS.workflow(name=CHECK_OBJECTS_WORKFLOW)
async def check_objects_workflow(_workflow_id: str, _owner_id: str) -> dict[str, Any]:
    return await check_objects_step()


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


@DBOS.step(retries_allowed=True, max_attempts=3)
async def recommend_tags_all_step(owner_id: str) -> dict[str, Any]:
    from quirebase.library import enqueue_all_item_tag_recommendations

    async with AsyncSessionLocal() as db:
        count = await enqueue_all_item_tag_recommendations(db, owner_id=owner_id)
        await db.commit()
        return {"enqueued_items": count}


@DBOS.workflow(name=RECOMMEND_TAGS_WORKFLOW)
async def recommend_tags_all_workflow(_workflow_id: str, owner_id: str) -> dict[str, Any]:
    return await recommend_tags_all_step(owner_id)
