"""Workspace-scoped document aggregate loaders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from quirebase.access.scope import workspace_select
from quirebase.models import Attachment, FileRevision, PdfAnnotation, PdfAnnotationReply

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.access.workspaces import WorkspaceContext


async def get_revision(
    db: AsyncSession, ctx: WorkspaceContext, revision_id: str
) -> FileRevision | None:
    return await db.scalar(
        workspace_select(FileRevision, ctx).where(FileRevision.id == revision_id)
    )


async def get_revision_for_update(
    db: AsyncSession, ctx: WorkspaceContext, revision_id: str
) -> FileRevision | None:
    return await db.scalar(
        workspace_select(FileRevision, ctx).where(FileRevision.id == revision_id).with_for_update()
    )


async def get_attachment(
    db: AsyncSession, ctx: WorkspaceContext, attachment_id: str
) -> Attachment | None:
    return await db.scalar(workspace_select(Attachment, ctx).where(Attachment.id == attachment_id))


async def get_annotation(
    db: AsyncSession, ctx: WorkspaceContext, annotation_id: str
) -> PdfAnnotation | None:
    return await db.scalar(
        workspace_select(PdfAnnotation, ctx).where(PdfAnnotation.id == annotation_id)
    )


async def get_annotation_reply(
    db: AsyncSession, ctx: WorkspaceContext, reply_id: str
) -> PdfAnnotationReply | None:
    return await db.scalar(
        workspace_select(PdfAnnotationReply, ctx).where(PdfAnnotationReply.id == reply_id)
    )
