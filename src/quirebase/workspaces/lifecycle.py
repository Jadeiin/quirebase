from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from quirebase.access import (
    ResourceAction,
    require_action,
    require_workspace_membership,
)
from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.errors import (
    ValidationFailure,
    WorkspaceLifecycleError,
)
from quirebase.core.workflows import (
    DOCUMENT_CLEANUP_QUEUE,
    durable_operations,
    object_reservation_attributes,
)
from quirebase.documents import delete_workspace_annotation_identities, snapshot_workspace_documents
from quirebase.models import User, Workspace, WorkspaceState
from quirebase.search import search_index

from .workflows import WORKSPACE_OBJECT_CLEANUP_WORKFLOW

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from ._locking import _lock_workspace


async def update_workspace(
    db: AsyncSession, actor: User, workspace_id: UUID, name: str
) -> Workspace:
    workspace = await _lock_workspace(db, workspace_id)
    context = await require_workspace_membership(db, actor, workspace_id)
    require_action(context, ResourceAction.workspace_update)
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


async def archive_workspace(db: AsyncSession, actor: User, workspace_id: UUID) -> Workspace:
    workspace = await _lock_workspace(db, workspace_id)
    context = await require_workspace_membership(db, actor, workspace_id)
    require_action(context, ResourceAction.workspace_archive)
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


async def restore_workspace(db: AsyncSession, actor: User, workspace_id: UUID) -> Workspace:
    # Restore is the one mutation intentionally authorized while archived.
    workspace = await _lock_workspace(db, workspace_id)
    if workspace.governance_frozen_at is not None:
        raise WorkspaceLifecycleError("Workspace writes are frozen")
    context = await require_workspace_membership(db, actor, workspace_id)
    require_action(context, ResourceAction.workspace_restore)
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
    db: AsyncSession, actor: User, workspace_id: UUID
) -> Workspace:
    # Deletion is permitted only from archived state, so membership and role are checked separately.
    workspace = await _lock_workspace(db, workspace_id)
    if workspace.governance_frozen_at is not None:
        raise WorkspaceLifecycleError("Workspace writes are frozen")
    context = await require_workspace_membership(db, actor, workspace_id)
    require_action(context, ResourceAction.workspace_delete)
    if workspace.state is not WorkspaceState.archived:
        raise ValidationFailure("Workspace must be archived before permanent deletion")
    now = datetime.now(UTC)
    archived_at = workspace.archived_at or None
    retention = timedelta(days=get_settings().workspace_delete_retention_days)
    if archived_at is None or archived_at > now - retention:
        raise WorkspaceLifecycleError("Workspace archive retention period has not elapsed")

    from quirebase.library import import_staging_object_keys

    documents = await snapshot_workspace_documents(db, workspace_id)
    object_keys = set(documents.object_keys)
    object_keys.update(await import_staging_object_keys(db, workspace_id=workspace_id))
    await search_index(db).remove_workspace(db, workspace_id)

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
                **object_reservation_attributes(batch_keys, intent="cleanup"),
            },
        )
    # Deleting the root is the database fence for in-flight stale mutations:
    # every Workspace-owned aggregate is connected by cascading foreign keys.
    await db.delete(workspace)
    await db.flush()
    await delete_workspace_annotation_identities(db, documents)
    await db.commit()
    return workspace
