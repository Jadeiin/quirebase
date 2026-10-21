"""Bounded expiration of the server-side Annotation Undo window."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete

from quirebase.core.persistence import delete_page
from quirebase.models import PdfAnnotation, PdfAnnotationReply

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


async def purge_deleted_annotations(db: AsyncSession, *, before: datetime, limit: int = 500) -> int:
    """Physically expire root records and their Replies in the caller's transaction."""
    return await delete_page(
        db,
        delete(PdfAnnotation).where(PdfAnnotation.deleted_at <= before),
        order_by=(PdfAnnotation.deleted_at, PdfAnnotation.id),
        limit=limit,
    )


async def purge_deleted_replies(db: AsyncSession, *, before: datetime, limit: int = 500) -> int:
    return await delete_page(
        db,
        delete(PdfAnnotationReply).where(PdfAnnotationReply.deleted_at <= before),
        order_by=(PdfAnnotationReply.deleted_at, PdfAnnotationReply.id),
        limit=limit,
    )
