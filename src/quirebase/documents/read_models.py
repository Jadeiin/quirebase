"""Immutable Document summaries for composite reads, without storage descriptors."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import load_only

from quirebase.core.workflows import durable_operations
from quirebase.models import Attachment, FileRevision, FileRevisionProcessingState

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import AttachmentRole


@dataclass(frozen=True, slots=True)
class DocumentInfo:
    id: UUID
    kind: Literal["revision", "attachment"]
    original_name: str
    mime_type: str
    size: int
    created_at: datetime
    page_count: int | None = None
    processing_state: FileRevisionProcessingState | None = None
    role: AttachmentRole | None = None


def document_info(document: FileRevision | Attachment) -> DocumentInfo:
    """Project an owned mapping while the read transaction is still open."""
    if document.file.size is None:
        raise ValueError("persisted Document requires a file size")
    return DocumentInfo(
        id=document.id,
        kind="revision" if isinstance(document, FileRevision) else "attachment",
        original_name=document.file.metadata["original_name"],
        mime_type=document.file.content_type or "application/octet-stream",
        size=document.file.size,
        created_at=document.created_at,
        page_count=document.page_count if isinstance(document, FileRevision) else None,
        processing_state=document.processing_state if isinstance(document, FileRevision) else None,
        role=document.role if isinstance(document, Attachment) else None,
    )


async def list_item_revisions(
    db: AsyncSession, workspace_id: UUID, item_id: UUID, *, all_revisions: bool = False
) -> tuple[DocumentInfo, ...]:
    """Read summaries for an authorized Item in the caller's transaction."""
    query = (
        select(FileRevision)
        .options(
            load_only(
                FileRevision.id,
                FileRevision.file,
                FileRevision.created_at,
                FileRevision.page_count,
                FileRevision.processing_state,
                FileRevision.processing_workflow_id,
            )
        )
        .where(FileRevision.workspace_id == workspace_id, FileRevision.item_id == item_id)
        .order_by(FileRevision.created_at.desc(), FileRevision.id)
    )
    if not all_revisions:
        query = query.limit(1)
    summaries = []
    for revision in await db.scalars(query):
        summary = document_info(revision)
        if revision.processing_state is FileRevisionProcessingState.pending:
            workflow = (
                await durable_operations().get(revision.processing_workflow_id)
                if revision.processing_workflow_id
                else None
            )
            if workflow is None or workflow.state not in {"pending", "running"}:
                summary = replace(
                    summary,
                    processing_state=FileRevisionProcessingState.failed,
                )
        summaries.append(summary)
    return tuple(summaries)


async def list_item_attachments(
    db: AsyncSession, workspace_id: UUID, item_id: UUID
) -> tuple[DocumentInfo, ...]:
    """Read attachment summaries for an authorized Item in the caller's transaction."""
    query = (
        select(Attachment)
        .where(Attachment.workspace_id == workspace_id, Attachment.item_id == item_id)
        .order_by(Attachment.created_at, Attachment.id)
    )
    return tuple(document_info(attachment) for attachment in await db.scalars(query))


async def count_item_attachments(db: AsyncSession, workspace_id: UUID, item_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count(Attachment.id)).where(
                Attachment.workspace_id == workspace_id, Attachment.item_id == item_id
            )
        )
        or 0
    )


async def count_item_revisions(db: AsyncSession, workspace_id: UUID, item_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count(FileRevision.id)).where(
                FileRevision.workspace_id == workspace_id, FileRevision.item_id == item_id
            )
        )
        or 0
    )
