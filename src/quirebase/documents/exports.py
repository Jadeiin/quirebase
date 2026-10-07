from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select

from quirebase.access import (
    ResourceAction,
    require_project_context,
    require_workspace_action,
)
from quirebase.access.documents import require_revision
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.core.storage import (
    ObjectResponse,
    ObjectSuffix,
    SignedDownload,
    get_object_store,
    object_key,
)
from quirebase.core.workflows import DOCUMENTS_QUEUE, durable_operations
from quirebase.models import ExportArtifact, ProjectItem, User

from .workflows import ANNOTATION_EXPORT_WORKFLOW

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.documents.schemas import ExportCreate


async def create_export_job(
    db: AsyncSession, user: User, workspace_id: UUID, item_id: UUID, data: ExportCreate
) -> str:
    revision = await require_revision(db, user, workspace_id, data.revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    if data.project_id:
        await require_project_context(
            db, user, workspace_id, data.project_id, ResourceAction.workspace_export
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
        object_id,
        data.project_id,
        data.include_private,
        data.timezone,
        queue_name=DOCUMENTS_QUEUE,
        workflow_id=workflow_id,
        partition_key=str(data.revision_id),
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


async def _workspace_export(user: User, workspace_id: UUID, workflow_id: str):
    workflow = await durable_operations().get(workflow_id)
    attributes = workflow.attributes if workflow else None
    if (
        workflow is None
        or workflow.name != ANNOTATION_EXPORT_WORKFLOW
        or not attributes
        or attributes.get("workspace_id") != str(workspace_id)
        or attributes.get("actor_id") != str(user.id)
    ):
        raise ResourceNotFound("export workflow not found")
    return workflow


async def get_export_status(
    db: AsyncSession, user: User, workspace_id: UUID, workflow_id: str
) -> dict[str, Any]:
    await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_export)
    workflow = await _workspace_export(user, workspace_id, workflow_id)
    return {"id": workflow.id, "state": workflow.state, "error": workflow.error}


async def get_export_file(
    db: AsyncSession, user: User, workspace_id: UUID, workflow_id: str
) -> ObjectResponse | SignedDownload:
    await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_export)
    workflow = await _workspace_export(user, workspace_id, workflow_id)
    if workflow.state != "succeeded" or not isinstance(workflow.output, dict):
        raise ResourceNotFound("export workflow not found or not ready")
    revision_id = workflow.output.get("revision_id")
    if not isinstance(revision_id, UUID):
        raise ResourceNotFound("export revision not found")
    revision = await require_revision(db, user, workspace_id, revision_id)
    project_id = workflow.output.get("project_id")
    if project_id:
        if not isinstance(project_id, UUID):
            raise ResourceNotFound("export project not found")
        await require_project_context(
            db, user, workspace_id, project_id, ResourceAction.workspace_export
        )
        project_item_id = workflow.output.get("project_item_id")
        if (
            not isinstance(project_item_id, UUID)
            or await db.scalar(
                select(ProjectItem.id).where(
                    ProjectItem.id == project_item_id,
                    ProjectItem.workspace_id == workspace_id,
                    ProjectItem.project_id == project_id,
                    ProjectItem.item_id == revision.item_id,
                )
            )
            is None
        ):
            raise ResourceUnavailable("project item not found")
    artifact = await db.scalar(
        select(ExportArtifact).where(
            ExportArtifact.workflow_id == workflow_id,
            ExportArtifact.workspace_id == workspace_id,
            ExportArtifact.expires_at > datetime.now(UTC),
        )
    )
    if artifact is None or not await get_object_store().exists(artifact.file.path):
        raise ResourceNotFound("export artifact expired or deleted")
    try:
        signed = await get_object_store().sign_download(
            artifact.file, expires_at=artifact.expires_at
        )
    except FileNotFoundError as error:
        raise ResourceNotFound("export artifact expired or deleted") from error
    return signed if signed is not None else await get_object_store().get(artifact.file.path)
