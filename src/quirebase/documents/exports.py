from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select

from quirebase.access.documents import require_revision
from quirebase.access.workspaces import (
    Capability,
    require_project_context,
    require_workspace_capability,
)
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.core.storage import ObjectResponse, ObjectSuffix, get_object_store, object_key
from quirebase.core.workflows import DOCUMENTS_QUEUE, durable_operations
from quirebase.models import ProjectItem, User

from .workflows import ANNOTATION_EXPORT_WORKFLOW

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.documents.schemas import ExportCreate


async def create_export_job(
    db: AsyncSession, user: User, workspace_id: str, item_id: str, data: ExportCreate
) -> str:
    revision = await require_revision(db, user, workspace_id, data.revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    if data.project_id:
        await require_project_context(
            db, user, workspace_id, data.project_id, Capability.workspace_export
        )
        project_item = await db.scalar(
            select(ProjectItem).where(
                ProjectItem.workspace_id == workspace_id,
                ProjectItem.project_id == data.project_id,
                ProjectItem.item_id == item_id,
            )
        )
        if project_item is None:
            raise ResourceUnavailable("Project item not found")
    object_id = uuid4()
    export_key = object_key(object_id, ObjectSuffix.PDF)
    workflow_id = f"annotation-export:{uuid4()}"
    await durable_operations().enqueue(
        ANNOTATION_EXPORT_WORKFLOW,
        user.id,
        workspace_id,
        data.revision_id,
        str(object_id),
        data.project_id,
        data.include_private,
        data.timezone,
        queue_name=DOCUMENTS_QUEUE,
        workflow_id=workflow_id,
        partition_key=data.revision_id,
        attributes={
            "capability": "documents",
            "operation": "annotation_export",
            "actor_id": user.id,
            "workspace_id": workspace_id,
            "item_id": item_id,
            "revision_id": data.revision_id,
            "object_keys": [export_key],
        },
    )
    return workflow_id


async def _workspace_export(user: User, workspace_id: str, workflow_id: str):
    workflow = await durable_operations().get(workflow_id)
    attributes = workflow.attributes if workflow else None
    if (
        workflow is None
        or workflow.name != ANNOTATION_EXPORT_WORKFLOW
        or not attributes
        or attributes.get("workspace_id") != workspace_id
        or attributes.get("actor_id") != user.id
    ):
        raise ResourceNotFound("export workflow not found")
    return workflow


async def get_export_status(
    db: AsyncSession, user: User, workspace_id: str, workflow_id: str
) -> dict[str, Any]:
    await require_workspace_capability(db, user, workspace_id, Capability.workspace_export)
    workflow = await _workspace_export(user, workspace_id, workflow_id)
    return {"id": workflow.id, "state": workflow.state, "error": workflow.error}


async def get_export_file(
    db: AsyncSession, user: User, workspace_id: str, workflow_id: str
) -> ObjectResponse:
    await require_workspace_capability(db, user, workspace_id, Capability.workspace_export)
    workflow = await _workspace_export(user, workspace_id, workflow_id)
    if workflow.state != "succeeded" or not isinstance(workflow.output, dict):
        raise ResourceNotFound("export workflow not found or not ready")
    revision = await require_revision(
        db, user, workspace_id, str(workflow.output.get("revision_id", ""))
    )
    project_id = workflow.output.get("project_id")
    if project_id:
        await require_project_context(
            db, user, workspace_id, str(project_id), Capability.workspace_export
        )
        if (
            await db.scalar(
                select(ProjectItem.id).where(
                    ProjectItem.workspace_id == workspace_id,
                    ProjectItem.project_id == str(project_id),
                    ProjectItem.item_id == revision.item_id,
                )
            )
            is None
        ):
            raise ResourceUnavailable("project item not found")
    key = workflow.output.get("object_key")
    if not isinstance(key, str) or not await get_object_store().exists(key):
        raise ResourceNotFound("export artifact expired or deleted")
    return await get_object_store().get(key)
