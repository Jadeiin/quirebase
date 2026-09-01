from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from quirebase.access.documents import require_revision
from quirebase.access.projects import project_member
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.core.storage import ObjectResponse, ObjectSuffix, get_object_store, object_key
from quirebase.core.workflows import DOCUMENTS_QUEUE, durable_operations
from quirebase.models import ProjectItem, User

from .workflows import ANNOTATION_EXPORT_WORKFLOW

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.documents.schemas import ExportCreate


async def create_export_job(db: AsyncSession, user: User, item_id: str, data: ExportCreate) -> str:
    revision = await require_revision(db, user, data.revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    if data.project_id and (
        await project_member(db, user, data.project_id) is None
        or await db.get(ProjectItem, (data.project_id, item_id)) is None
    ):
        raise ResourceUnavailable("project membership or project item not found")
    object_id = uuid4()
    export_key = object_key(object_id, ObjectSuffix.PDF)
    workflow_id = f"annotation-export:{uuid4()}"
    await durable_operations().enqueue(
        ANNOTATION_EXPORT_WORKFLOW,
        user.id,
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
            "owner_id": user.id,
            "item_id": item_id,
            "revision_id": data.revision_id,
            "object_keys": [export_key],
        },
    )
    return workflow_id


async def _owned_export(user: User, workflow_id: str):
    workflow = await durable_operations().get(workflow_id)
    attributes = workflow.attributes if workflow else None
    if (
        workflow is None
        or workflow.name != ANNOTATION_EXPORT_WORKFLOW
        or not attributes
        or attributes.get("owner_id") != user.id
    ):
        raise ResourceNotFound("export workflow not found")
    return workflow


async def get_export_status(db: AsyncSession, user: User, workflow_id: str) -> dict[str, Any]:
    del db
    workflow = await _owned_export(user, workflow_id)
    return {"id": workflow.id, "state": workflow.state, "error": workflow.error}


async def get_export_file(db: AsyncSession, user: User, workflow_id: str) -> ObjectResponse:
    workflow = await _owned_export(user, workflow_id)
    if workflow.state != "succeeded" or not isinstance(workflow.output, dict):
        raise ResourceNotFound("export workflow not found or not ready")
    revision = await require_revision(db, user, str(workflow.output.get("revision_id", "")))
    project_id = workflow.output.get("project_id")
    if project_id and (
        await project_member(db, user, project_id) is None
        or await db.get(ProjectItem, (project_id, revision.item_id)) is None
    ):
        raise ResourceUnavailable("project membership or project item not found")
    key = workflow.output.get("object_key")
    if not isinstance(key, str) or not await get_object_store().exists(key):
        raise ResourceNotFound("export artifact expired or deleted")
    return await get_object_store().get(key)
