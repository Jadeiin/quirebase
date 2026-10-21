"""Durable physical cleanup after an authorized Workspace deletion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dbos import DBOS

from quirebase.core.database import AsyncSessionLocal
from quirebase.documents import delete_unreferenced_objects
from quirebase.models import Workspace

if TYPE_CHECKING:
    from uuid import UUID

WORKSPACE_OBJECT_CLEANUP_WORKFLOW = "workspaces.cleanup_deleted_objects"


@DBOS.step(retries_allowed=True, max_attempts=3)
async def cleanup_deleted_workspace_objects_step(
    workflow_id: str, actor_id: UUID, workspace_id: UUID, object_keys: list[str]
) -> list[str]:
    async with AsyncSessionLocal() as db:
        if await db.get(Workspace, workspace_id) is not None:
            raise ValueError("Workspace deletion has not committed")
        # Authorization and enqueue commit atomically with root deletion. Audit
        # history has its own retention period and is never execution authority.
        return list(
            await delete_unreferenced_objects(db, object_keys, ignore_workflow_id=workflow_id)
        )


@DBOS.workflow(name=WORKSPACE_OBJECT_CLEANUP_WORKFLOW)
async def cleanup_deleted_workspace_objects_workflow(
    workflow_id: str, actor_id: UUID, workspace_id: UUID, object_keys: list[str]
) -> dict[str, int]:
    deleted = await cleanup_deleted_workspace_objects_step(
        workflow_id, actor_id, workspace_id, object_keys
    )
    return {"deleted_objects": len(deleted)}
