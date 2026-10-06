from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import delete, select, text

from quirebase.access import (
    ResourceAction,
    require_workspace_action,
)
from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.errors import (
    ValidationFailure,
    WorkspaceLifecycleError,
)
from quirebase.core.timezones import as_utc
from quirebase.core.workflows import DOCUMENT_CLEANUP_QUEUE, durable_operations
from quirebase.models import (
    Attachment,
    ExportArtifact,
    FileRevision,
    ImportBatch,
    PdfAnnotation,
    PdfAnnotationObject,
    PdfAnnotationReply,
    User,
    Workspace,
    WorkspaceState,
)

from .workflows import WORKSPACE_OBJECT_CLEANUP_WORKFLOW

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from ._locking import _lock_workspace


async def update_workspace(
    db: AsyncSession, actor: User, workspace_id: str, name: str
) -> Workspace:
    workspace = await _lock_workspace(db, workspace_id)
    context = await require_workspace_action(
        db, actor, workspace_id, ResourceAction.workspace_update
    )
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 240:
        raise ValidationFailure("Workspace name must contain 1 to 240 characters")
    workspace.name = cleaned
    record_event(
        db,
        actor.id,
        "workspace.update",
        "workspace",
        workspace.id,
        workspace_id=workspace.id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.workspace_update.value,
    )
    await db.commit()
    return workspace


async def archive_workspace(db: AsyncSession, actor: User, workspace_id: str) -> Workspace:
    workspace = await _lock_workspace(db, workspace_id)
    context = await require_workspace_action(
        db, actor, workspace_id, ResourceAction.workspace_archive
    )
    workspace.state = WorkspaceState.archived
    workspace.archived_at = datetime.now(UTC)
    record_event(
        db,
        actor.id,
        "workspace.archive",
        "workspace",
        workspace.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.workspace_archive.value,
    )
    await db.commit()
    return workspace


async def restore_workspace(db: AsyncSession, actor: User, workspace_id: str) -> Workspace:
    # Restore is the one mutation intentionally authorized while archived.
    workspace = await _lock_workspace(db, workspace_id)
    if workspace.governance_suspended_at is not None:
        raise WorkspaceLifecycleError("Workspace governance is suspended")
    context = await require_workspace_action(
        db, actor, workspace_id, ResourceAction.workspace_restore
    )
    workspace.state = WorkspaceState.active
    workspace.archived_at = None
    record_event(
        db,
        actor.id,
        "workspace.restore",
        "workspace",
        workspace.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.workspace_restore.value,
    )
    await db.commit()
    return workspace


async def permanently_delete_workspace(
    db: AsyncSession, actor: User, workspace_id: str
) -> Workspace:
    # Deletion is permitted only from archived state, so membership and role are checked separately.
    workspace = await _lock_workspace(db, workspace_id)
    if workspace.governance_suspended_at is not None:
        raise WorkspaceLifecycleError("Workspace governance is suspended")
    context = await require_workspace_action(
        db, actor, workspace_id, ResourceAction.workspace_delete
    )
    if workspace.state is not WorkspaceState.archived:
        raise ValidationFailure("Workspace must be archived before permanent deletion")
    now = datetime.now(UTC)
    archived_at = as_utc(workspace.archived_at) if workspace.archived_at else None
    retention = timedelta(days=get_settings().workspace_delete_retention_days)
    if archived_at is None or archived_at > now - retention:
        raise WorkspaceLifecycleError("Workspace archive retention period has not elapsed")

    object_keys = set(
        (
            await db.scalars(
                select(FileRevision.object_key).where(FileRevision.workspace_id == workspace_id)
            )
        ).all()
    )
    object_keys.update(
        key
        for key in (
            await db.scalars(
                select(FileRevision.thumbnail_object_key).where(
                    FileRevision.workspace_id == workspace_id,
                    FileRevision.thumbnail_object_key.is_not(None),
                )
            )
        ).all()
        if key
    )
    object_keys.update(
        (
            await db.scalars(
                select(Attachment.object_key).where(Attachment.workspace_id == workspace_id)
            )
        ).all()
    )
    object_keys.update(
        (
            await db.scalars(
                select(ExportArtifact.object_key).where(ExportArtifact.workspace_id == workspace_id)
            )
        ).all()
    )
    for records_json in (
        await db.scalars(
            select(ImportBatch.records).where(ImportBatch.workspace_id == workspace_id)
        )
    ).all():
        try:
            records = json.loads(records_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValidationFailure("Workspace Import Batch records are invalid") from error
        if not isinstance(records, list):
            raise ValidationFailure("Workspace Import Batch records are invalid")
        for record in records:
            if isinstance(record, dict) and isinstance((pdf := record.get("_pdf")), dict):
                key = pdf.get("object_key")
                if isinstance(key, str):
                    object_keys.add(key)

    annotation_ids = list(
        (
            await db.scalars(
                select(PdfAnnotation.id).where(PdfAnnotation.workspace_id == workspace_id)
            )
        ).all()
    )
    annotation_ids.extend(
        (
            await db.scalars(
                select(PdfAnnotationReply.id).where(PdfAnnotationReply.workspace_id == workspace_id)
            )
        ).all()
    )
    # SQLite FTS tables have no foreign keys; PostgreSQL's projections do, but
    # explicit removal keeps both dialects identical before the root cascade.
    await db.execute(
        text(
            "DELETE FROM revision_search WHERE item_id IN "
            "(SELECT id FROM items WHERE workspace_id = :workspace_id)"
        ),
        {"workspace_id": workspace_id},
    )
    await db.execute(
        text(
            "DELETE FROM item_search WHERE item_id IN "
            "(SELECT id FROM items WHERE workspace_id = :workspace_id)"
        ),
        {"workspace_id": workspace_id},
    )

    workspace.state = WorkspaceState.deleted
    workspace.deleted_at = now
    record_event(
        db,
        actor.id,
        "workspace.delete",
        "workspace",
        workspace.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.workspace_delete.value,
    )
    sorted_keys = sorted(object_keys)
    for start in range(0, len(sorted_keys), 200):
        batch_keys = sorted_keys[start : start + 200]
        workflow_id = f"workspace-objects-cleanup:{uuid4()}"
        await durable_operations().enqueue_in_transaction(
            db,
            WORKSPACE_OBJECT_CLEANUP_WORKFLOW,
            workflow_id,
            actor.id,
            workspace_id,
            batch_keys,
            queue_name=DOCUMENT_CLEANUP_QUEUE,
            workflow_id=workflow_id,
            attributes={
                "capability": "workspaces",
                "operation": "workspace_delete_cleanup",
                "actor_id": actor.id,
                "workspace_id": workspace_id,
                "object_keys": batch_keys,
            },
        )
    # Deleting the root is the database fence for in-flight stale mutations:
    # every Workspace-owned aggregate is connected by cascading foreign keys.
    await db.delete(workspace)
    await db.flush()
    for start in range(0, len(annotation_ids), 500):
        await db.execute(
            delete(PdfAnnotationObject).where(
                PdfAnnotationObject.id.in_(annotation_ids[start : start + 500])
            )
        )
    await db.commit()
    return workspace
