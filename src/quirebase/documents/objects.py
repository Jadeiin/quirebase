"""Document object references, safe physical deletion and Workspace teardown facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from quirebase.core.storage import get_object_store
from quirebase.core.workflows import active_object_reservations
from quirebase.models import (
    Attachment,
    ExportArtifact,
    FileRevision,
    PdfAnnotation,
    PdfAnnotationObject,
    PdfAnnotationReply,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def _document_object_keys(
    db: AsyncSession, keys: Iterable[str] | None = None, *, workspace_id: UUID | None = None
) -> set[str]:
    candidates = set(keys) if keys is not None else None
    referenced: set[str] = set()
    for model, descriptor in (
        (FileRevision, FileRevision.file),
        (FileRevision, FileRevision.thumbnail),
        (Attachment, Attachment.file),
        (ExportArtifact, ExportArtifact.file),
    ):
        filename = descriptor["filename"].as_string()
        query = select(filename).where(filename.is_not(None))
        if candidates is not None:
            query = query.where(filename.in_(candidates))
        if workspace_id is not None:
            query = query.where(model.workspace_id == workspace_id)
        referenced.update(await db.scalars(query))
    return referenced


async def referenced_object_keys(db: AsyncSession, keys: Iterable[str] | None = None) -> set[str]:
    """Read Document descriptors and Library's retained staging in the caller transaction."""
    # Resolve the facade at execution time; Library's imports consume Documents.
    from quirebase.library import import_staging_object_keys

    candidates = set(keys) if keys is not None else None
    # Staging is released into committed File Revisions in one transaction. Read
    # that source first, then its destinations, so READ COMMITTED cannot miss a
    # confirmation that moves ownership between these two statements.
    staged = await import_staging_object_keys(db)
    referenced = staged if candidates is None else candidates & staged
    referenced.update(await _document_object_keys(db, candidates))
    return referenced


async def protected_object_keys(
    db: AsyncSession, keys: Iterable[str] | None = None, *, ignore_workflow_id: str | None = None
) -> set[str]:
    """Fresh read-only check; the session must have no pending caller writes.

    Check reservations before opening a fresh descriptor read. A workflow that completes
    during this check is protected either by its reservation or its committed descriptor.
    The workflow-first UUID protocol forbids introducing ownership of an old orphan key.
    """
    candidates = set(keys) if keys is not None else None
    await db.rollback()
    reserved = await active_object_reservations(ignore_workflow_id=ignore_workflow_id)
    referenced = await referenced_object_keys(db, candidates)
    await db.rollback()
    return referenced | (reserved if candidates is None else reserved & candidates)


async def delete_unreferenced_objects(
    db: AsyncSession, object_keys: Iterable[str], *, ignore_workflow_id: str | None = None
) -> tuple[str, ...]:
    """Recheck each object immediately before I/O; retries tolerate already absent objects."""
    deleted: list[str] = []
    store = get_object_store()
    for key in dict.fromkeys(key for key in object_keys if key):
        if key in await protected_object_keys(db, (key,), ignore_workflow_id=ignore_workflow_id):
            continue
        if await store.delete(key):
            deleted.append(key)
    return tuple(deleted)


async def list_expired_export_artifacts(db: AsyncSession, limit: int) -> tuple[dict[str, str], ...]:
    rows = await db.execute(
        select(ExportArtifact.workflow_id, ExportArtifact.file["filename"].as_string())
        .where(ExportArtifact.expires_at <= datetime.now(UTC))
        .order_by(ExportArtifact.expires_at, ExportArtifact.workflow_id)
        .limit(limit)
    )
    return tuple({"workflow_id": identity, "object_key": key} for identity, key in rows)


async def retire_expired_export_artifacts(
    db: AsyncSession, artifacts: tuple[dict[str, str], ...]
) -> tuple[str, ...]:
    """Release still-expired, matching descriptors; caller checkpoints keys atomically with commit.

    Physical deletion runs afterwards through the ordinary reference protection. Replayed
    checkpoints retain the retired keys even when these rows have already disappeared.
    """
    keys: list[str] = []
    for artifact in artifacts:
        key = await db.scalar(
            delete(ExportArtifact)
            .where(
                ExportArtifact.workflow_id == artifact["workflow_id"],
                ExportArtifact.file["filename"].as_string() == artifact["object_key"],
                ExportArtifact.expires_at <= datetime.now(UTC),
            )
            .returning(ExportArtifact.file["filename"].as_string())
        )
        if key is not None:
            keys.append(key)
    return tuple(dict.fromkeys(keys))


@dataclass(frozen=True)
class WorkspaceDocumentSnapshot:
    object_keys: frozenset[str]
    annotation_ids: tuple[UUID, ...]


async def snapshot_workspace_documents(
    db: AsyncSession, workspace_id: UUID
) -> WorkspaceDocumentSnapshot:
    """Snapshot Document teardown under the caller's exclusive Workspace root lock."""
    keys = await _document_object_keys(db, workspace_id=workspace_id)
    identities: list[UUID] = []
    for model in (PdfAnnotation, PdfAnnotationReply):
        identities.extend(
            await db.scalars(select(model.id).where(model.workspace_id == workspace_id))
        )
    return WorkspaceDocumentSnapshot(frozenset(keys), tuple(identities))


async def delete_workspace_annotation_identities(
    db: AsyncSession, snapshot: WorkspaceDocumentSnapshot
) -> None:
    """Remove captured identities after the root cascade, in the same caller transaction."""
    for start in range(0, len(snapshot.annotation_ids), 500):
        await db.execute(
            delete(PdfAnnotationObject).where(
                PdfAnnotationObject.id.in_(snapshot.annotation_ids[start : start + 500])
            )
        )
