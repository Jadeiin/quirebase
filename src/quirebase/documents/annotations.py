from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from quirebase.access.annotations import require_editable_annotation
from quirebase.access.documents import require_revision
from quirebase.access.projects import project_member
from quirebase.audit import record_event
from quirebase.core.errors import (
    DomainError,
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
    VersionConflict,
)
from quirebase.models import (
    AnnotationScope,
    FileRevision,
    FileRevisionProcessingState,
    PdfAnnotation,
    PdfAnnotationSegment,
    ProjectItem,
    User,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.documents.schemas import AnnotationCreate, AnnotationUpdate


class DocumentNotReady(DomainError):
    pass


def annotation_json(record: PdfAnnotation, current_user_id: str) -> dict[str, Any]:
    return {
        "id": record.id,
        "revision_id": record.file_revision_id,
        "kind": record.kind,
        "scope": record.scope,
        "project_id": record.project_id,
        "color": record.color,
        "body": record.body,
        "selected_text": record.selected_text,
        "version": record.version,
        "mine": record.author_id == current_user_id,
        "segments": [
            {
                "page_index": segment.page_index,
                "quad_points": [
                    segment.x1,
                    segment.y1,
                    segment.x2,
                    segment.y2,
                    segment.x3,
                    segment.y3,
                    segment.x4,
                    segment.y4,
                ]
                if segment.x1 is not None
                else None,
                "anchor_x": segment.anchor_x,
                "anchor_y": segment.anchor_y,
            }
            for segment in record.segments
        ],
    }


def validate_segments(data: AnnotationCreate, revision: FileRevision) -> None:
    if (
        revision.page_count is None
        or revision.processing_state != FileRevisionProcessingState.ready
    ):
        raise DocumentNotReady("PDF is not ready")
    geometry = json.loads(revision.page_geometry or "[]")
    if len(geometry) != revision.page_count:
        raise DocumentNotReady("PDF geometry is not ready")
    for segment in data.segments:
        if segment.page_index >= revision.page_count:
            raise ValidationFailure("page index is outside the document")
        values = list(segment.quad_points or [])
        if segment.anchor_x is not None:
            values.append(segment.anchor_x)
        if segment.anchor_y is not None:
            values.append(segment.anchor_y)
        if any(not (-1_000_000 < value < 1_000_000) for value in values):
            raise ValidationFailure("invalid PDF coordinates")
        left, bottom, right, top = geometry[segment.page_index]
        if segment.quad_points is not None:
            xs: Sequence[float | None] = segment.quad_points[0::2]
            ys: Sequence[float | None] = segment.quad_points[1::2]
        else:
            xs = [segment.anchor_x]
            ys = [segment.anchor_y]
        tolerance = 2.0
        if any(
            value is None or value < left - tolerance or value > right + tolerance for value in xs
        ):
            raise ValidationFailure("annotation is outside the PDF page")
        if any(
            value is None or value < bottom - tolerance or value > top + tolerance for value in ys
        ):
            raise ValidationFailure("annotation is outside the PDF page")


async def select_visible_annotations(
    db: AsyncSession,
    user: User,
    revision_id: str,
    item_id: str,
    project_id: str | None = None,
) -> list[PdfAnnotation]:
    """Load the annotations visible to one user: own private ones, plus a project's."""
    scopes = [
        and_(PdfAnnotation.scope == AnnotationScope.private, PdfAnnotation.author_id == user.id)
    ]
    if project_id:
        if (
            await project_member(db, user, project_id) is None
            or await db.get(ProjectItem, (project_id, item_id)) is None
        ):
            raise ResourceUnavailable("project membership or project item not found")
        scopes.append(
            and_(
                PdfAnnotation.scope == AnnotationScope.project,
                PdfAnnotation.project_id == project_id,
            )
        )
    return list(
        (
            await db.scalars(
                select(PdfAnnotation)
                .options(selectinload(PdfAnnotation.segments))
                .where(
                    PdfAnnotation.file_revision_id == revision_id,
                    PdfAnnotation.deleted_at.is_(None),
                    or_(*scopes),
                )
                .order_by(PdfAnnotation.created_at)
            )
        ).all()
    )


async def list_document_annotations(
    db: AsyncSession,
    user: User,
    item_id: str,
    revision_id: str,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    revision = await require_revision(db, user, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    records = await select_visible_annotations(db, user, revision_id, item_id, project_id)
    return [annotation_json(row, user.id) for row in records]


async def create_document_annotation(
    db: AsyncSession,
    user: User,
    item_id: str,
    data: AnnotationCreate,
) -> dict[str, Any]:
    revision = await require_revision(db, user, data.revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    if data.scope is AnnotationScope.project and (
        await project_member(db, user, data.project_id) is None
        or await db.get(ProjectItem, (data.project_id, item_id)) is None
    ):
        raise ResourceUnavailable("project membership or project item not found")
    validate_segments(data, revision)
    record = PdfAnnotation(
        file_revision_id=data.revision_id,
        author_id=user.id,
        kind=data.kind,
        scope=data.scope,
        project_id=data.project_id,
        color=data.color,
        body=data.body,
        selected_text=data.selected_text,
    )
    for ordinal, segment in enumerate(data.segments):
        values: Sequence[float | None] = segment.quad_points or [None] * 8
        record.segments.append(
            PdfAnnotationSegment(
                page_index=segment.page_index,
                ordinal=ordinal,
                x1=values[0],
                y1=values[1],
                x2=values[2],
                y2=values[3],
                x3=values[4],
                y3=values[5],
                x4=values[6],
                y4=values[7],
                anchor_x=segment.anchor_x,
                anchor_y=segment.anchor_y,
            )
        )
    db.add(record)
    await db.flush()
    record_event(db, user.id, "annotation.create", "pdf_annotation", record.id)
    await db.commit()
    return annotation_json(record, user.id)


async def update_document_annotation(
    db: AsyncSession,
    user: User,
    item_id: str,
    annotation_id: str,
    data: AnnotationUpdate,
) -> dict[str, Any]:
    record = await require_editable_annotation(db, user, item_id, annotation_id)
    if record.version != data.version:
        raise VersionConflict(record.version)
    if data.scope is not None:
        record.scope = data.scope
        record.project_id = data.project_id if data.scope is AnnotationScope.project else None
        if record.scope == AnnotationScope.project and (
            await project_member(db, user, record.project_id) is None
            or await db.get(ProjectItem, (record.project_id, item_id)) is None
        ):
            raise ResourceUnavailable("project membership or project item not found")
    if data.color is not None:
        record.color = data.color
    if data.body is not None:
        record.body = data.body
    record.version += 1
    record_event(db, user.id, "annotation.update", "pdf_annotation", record.id)
    await db.commit()
    return annotation_json(record, user.id)


async def delete_document_annotation(
    db: AsyncSession,
    user: User,
    item_id: str,
    annotation_id: str,
) -> None:
    record = await require_editable_annotation(db, user, item_id, annotation_id)
    record.deleted_at = datetime.now(UTC)
    record.version += 1
    record_event(db, user.id, "annotation.delete", "pdf_annotation", record.id)
    await db.commit()
