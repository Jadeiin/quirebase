from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from quirebase.access.annotations import (
    editable_annotation_ids,
    editable_annotation_reply_ids,
    require_editable_annotation,
    require_restorable_annotation,
    require_visible_annotation_for_reply_mutation,
)
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
from quirebase.documents.schemas import ArrowPayload, InkPayload, LinePayload, TextMarkupPayload
from quirebase.models import (
    AnnotationScope,
    FileRevision,
    FileRevisionProcessingState,
    PdfAnnotation,
    PdfAnnotationReply,
    ProjectItem,
    SystemRole,
    User,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.documents.schemas import (
        AnnotationCreate,
        AnnotationPayload,
        AnnotationReplyCreate,
        AnnotationReplyUpdate,
        AnnotationUpdate,
    )


class DocumentNotReady(DomainError):
    pass


def annotation_json(
    record: PdfAnnotation,
    current_user_id: str,
    *,
    author_display_name: str,
    editable: bool,
    replies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "revision_id": record.file_revision_id,
        "page_index": record.page_index,
        "kind": record.kind,
        "scope": record.scope,
        "project_id": record.project_id,
        "body": record.body,
        "selected_text": record.selected_text,
        "payload": record.payload,
        "version": record.version,
        "author_display_name": author_display_name,
        "mine": record.author_id == current_user_id,
        "editable": editable,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "replies": replies or [],
    }


def annotation_reply_json(
    record: PdfAnnotationReply,
    current_user_id: str,
    *,
    author_display_name: str,
    editable: bool,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "annotation_id": record.annotation_id,
        "body": record.body,
        "version": record.version,
        "author_display_name": author_display_name,
        "mine": record.author_id == current_user_id,
        "editable": editable,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def _page_size(revision: FileRevision, page_index: int) -> tuple[float, float]:
    if (
        revision.page_count is None
        or revision.processing_state != FileRevisionProcessingState.ready
    ):
        raise DocumentNotReady("PDF is not ready")
    try:
        geometry = json.loads(revision.page_geometry or "[]")
    except (TypeError, json.JSONDecodeError) as error:
        raise DocumentNotReady("PDF geometry is not ready") from error
    if len(geometry) != revision.page_count:
        raise DocumentNotReady("PDF geometry is not ready")
    if page_index >= revision.page_count:
        raise ValidationFailure("page index is outside the document")
    left, bottom, right, top = geometry[page_index]
    return float(right) - float(left), float(top) - float(bottom)


def validate_payload(page_index: int, payload: AnnotationPayload, revision: FileRevision) -> None:
    width, height = _page_size(revision, page_index)
    page_tolerance = 2.0
    enclosure_tolerance = 1e-6

    def check_rect(rect) -> None:
        if (
            rect.x + rect.width > width + page_tolerance
            or rect.y + rect.height > height + page_tolerance
        ):
            raise ValidationFailure("annotation is outside the PDF page")

    def check_point(point) -> None:
        if not (-page_tolerance <= point.x <= width + page_tolerance) or not (
            -page_tolerance <= point.y <= height + page_tolerance
        ):
            raise ValidationFailure("annotation is outside the PDF page")

    def check_enclosed_point(point) -> None:
        if not (
            payload.rect.x - enclosure_tolerance
            <= point.x
            <= payload.rect.x + payload.rect.width + enclosure_tolerance
            and payload.rect.y - enclosure_tolerance
            <= point.y
            <= payload.rect.y + payload.rect.height + enclosure_tolerance
        ):
            raise ValidationFailure("annotation geometry is outside its enclosing rectangle")

    def check_enclosed_rect(rect) -> None:
        check_enclosed_point(rect)
        if (
            rect.x + rect.width > payload.rect.x + payload.rect.width + enclosure_tolerance
            or rect.y + rect.height > payload.rect.y + payload.rect.height + enclosure_tolerance
        ):
            raise ValidationFailure("annotation geometry is outside its enclosing rectangle")

    check_rect(payload.rect)
    if isinstance(payload, TextMarkupPayload):
        for rect in payload.segment_rects:
            check_rect(rect)
            check_enclosed_rect(rect)
    if isinstance(payload, InkPayload):
        for path in payload.paths:
            for point in path:
                check_point(point)
                check_enclosed_point(point)
    if isinstance(payload, (LinePayload, ArrowPayload)):
        check_point(payload.start)
        check_point(payload.end)
        check_enclosed_point(payload.start)
        check_enclosed_point(payload.end)


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
                .where(
                    PdfAnnotation.file_revision_id == revision_id,
                    PdfAnnotation.deleted_at.is_(None),
                    or_(*scopes),
                )
                .order_by(PdfAnnotation.created_at, PdfAnnotation.id)
            )
        ).all()
    )


async def _annotation_views(
    db: AsyncSession, user: User, records: list[PdfAnnotation]
) -> list[dict[str, Any]]:
    if not records:
        return []
    annotation_ids = {record.id for record in records}
    replies = list(
        (
            await db.scalars(
                select(PdfAnnotationReply)
                .where(
                    PdfAnnotationReply.annotation_id.in_(annotation_ids),
                    PdfAnnotationReply.deleted_at.is_(None),
                )
                .order_by(PdfAnnotationReply.created_at, PdfAnnotationReply.id)
            )
        ).all()
    )
    author_ids = {record.author_id for record in records} | {
        reply.author_id for reply in replies
    }
    author_rows = (
        await db.execute(
            select(User.id, User.username).where(User.id.in_(author_ids))
        )
    ).all()
    authors: dict[str, str] = {row[0]: row[1] for row in author_rows}
    editable_ids = await editable_annotation_ids(db, user, records)
    records_by_id = {record.id: record for record in records}
    editable_reply_ids = await editable_annotation_reply_ids(db, user, replies, records_by_id)
    replies_by_annotation: dict[str, list[dict[str, Any]]] = {
        annotation_id: [] for annotation_id in annotation_ids
    }
    for reply in replies:
        replies_by_annotation[reply.annotation_id].append(
            annotation_reply_json(
                reply,
                user.id,
                author_display_name=authors.get(reply.author_id, ""),
                editable=reply.id in editable_reply_ids,
            )
        )
    return [
        annotation_json(
            record,
            user.id,
            author_display_name=authors.get(record.author_id, ""),
            editable=record.id in editable_ids,
            replies=replies_by_annotation[record.id],
        )
        for record in records
    ]


async def _editable_reply(
    db: AsyncSession,
    user: User,
    item_id: str,
    annotation_id: str,
    reply_id: str,
) -> tuple[PdfAnnotation, PdfAnnotationReply]:
    locked_user, annotation = await require_visible_annotation_for_reply_mutation(
        db, user, item_id, annotation_id
    )
    reply = await db.scalar(
        select(PdfAnnotationReply).where(
            PdfAnnotationReply.id == reply_id,
            PdfAnnotationReply.annotation_id == annotation_id,
            PdfAnnotationReply.deleted_at.is_(None),
        ).with_for_update()
    )
    if reply is None:
        raise ResourceUnavailable("annotation reply not found or cannot be edited")
    editable_ids = await editable_annotation_reply_ids(
        db, locked_user, [reply], {annotation.id: annotation}
    )
    if reply.id not in editable_ids:
        raise ResourceUnavailable("annotation reply not found or cannot be edited")
    return annotation, reply


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
    return await _annotation_views(db, user, records)


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
    validate_payload(data.page_index, data.payload, revision)
    object_id = str(data.id)
    record = PdfAnnotation(
        id=object_id,
        file_revision_id=data.revision_id,
        page_index=data.page_index,
        author_id=user.id,
        kind=data.kind,
        scope=data.scope,
        project_id=data.project_id,
        body=data.body,
        selected_text=data.selected_text,
        payload=data.payload.model_dump(mode="json"),
    )
    try:
        async with db.begin_nested():
            db.add(record)
            await db.flush()
    except IntegrityError as error:
        raise VersionConflict(message="annotation object ID already exists") from error
    record_event(db, user.id, "annotation.create", "pdf_annotation", record.id)
    await db.commit()
    return annotation_json(
        record,
        user.id,
        author_display_name=user.username,
        editable=True,
    )


async def update_document_annotation(
    db: AsyncSession,
    user: User,
    item_id: str,
    annotation_id: str,
    data: AnnotationUpdate,
) -> dict[str, Any]:
    record = await require_editable_annotation(db, user, item_id, annotation_id)
    revision = await db.get(FileRevision, record.file_revision_id)
    if revision is None:
        raise ResourceNotFound("revision not found")
    if data.scope is AnnotationScope.project and (
        await db.get(ProjectItem, (data.project_id, item_id)) is None
        or (
            user.role != SystemRole.administrator.value
            and await project_member(db, user, data.project_id) is None
        )
    ):
        raise ResourceUnavailable("project membership or project item not found")
    validate_payload(data.page_index, data.payload, revision)
    new_version = await db.scalar(
        update(PdfAnnotation)
        .where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.version == data.version,
            PdfAnnotation.deleted_at.is_(None),
        )
        .values(
            page_index=data.page_index,
            kind=data.kind,
            scope=data.scope,
            project_id=data.project_id,
            body=data.body,
            selected_text=data.selected_text,
            payload=data.payload.model_dump(mode="json"),
            version=PdfAnnotation.version + 1,
            updated_at=datetime.now(UTC),
        )
        .returning(PdfAnnotation.version)
    )
    if new_version is None:
        current_version = await db.scalar(
            select(PdfAnnotation.version).where(PdfAnnotation.id == annotation_id)
        )
        raise VersionConflict(current_version)
    await db.refresh(record)
    record_event(db, user.id, "annotation.update", "pdf_annotation", record.id)
    await db.commit()
    return (await _annotation_views(db, user, [record]))[0]


async def delete_document_annotation(
    db: AsyncSession,
    user: User,
    item_id: str,
    annotation_id: str,
    version: int,
) -> None:
    record = await require_editable_annotation(db, user, item_id, annotation_id)
    deleted_at = datetime.now(UTC)
    new_version = await db.scalar(
        update(PdfAnnotation)
        .where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.version == version,
            PdfAnnotation.deleted_at.is_(None),
        )
        .values(
            deleted_at=deleted_at,
            updated_at=deleted_at,
            version=PdfAnnotation.version + 1,
        )
        .returning(PdfAnnotation.version)
    )
    if new_version is None:
        current_version = await db.scalar(
            select(PdfAnnotation.version).where(PdfAnnotation.id == annotation_id)
        )
        raise VersionConflict(current_version)
    record_event(db, user.id, "annotation.delete", "pdf_annotation", record.id)
    await db.commit()


async def restore_document_annotation(
    db: AsyncSession,
    user: User,
    item_id: str,
    annotation_id: str,
    version: int,
) -> dict[str, Any]:
    record = await require_restorable_annotation(db, user, item_id, annotation_id)
    restored_at = datetime.now(UTC)
    new_version = await db.scalar(
        update(PdfAnnotation)
        .where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.version == version,
            PdfAnnotation.deleted_at.is_not(None),
        )
        .values(
            deleted_at=None,
            updated_at=restored_at,
            version=PdfAnnotation.version + 1,
        )
        .returning(PdfAnnotation.version)
    )
    if new_version is None:
        current_version = await db.scalar(
            select(PdfAnnotation.version).where(PdfAnnotation.id == annotation_id)
        )
        raise VersionConflict(current_version)
    await db.refresh(record)
    record_event(db, user.id, "annotation.restore", "pdf_annotation", record.id)
    await db.commit()
    return (await _annotation_views(db, user, [record]))[0]


async def create_annotation_reply(
    db: AsyncSession,
    user: User,
    item_id: str,
    annotation_id: str,
    data: AnnotationReplyCreate,
) -> dict[str, Any]:
    locked_user, _annotation = await require_visible_annotation_for_reply_mutation(
        db, user, item_id, annotation_id
    )
    object_id = str(data.id)
    record = PdfAnnotationReply(
        id=object_id,
        annotation_id=annotation_id,
        author_id=locked_user.id,
        body=data.body,
    )
    try:
        async with db.begin_nested():
            db.add(record)
            await db.flush()
    except IntegrityError as error:
        raise VersionConflict(message="annotation object ID already exists") from error
    record_event(
        db, locked_user.id, "annotation_reply.create", "pdf_annotation_reply", record.id
    )
    await db.commit()
    return annotation_reply_json(
        record,
        locked_user.id,
        author_display_name=locked_user.username,
        editable=True,
    )


async def update_annotation_reply(
    db: AsyncSession,
    user: User,
    item_id: str,
    annotation_id: str,
    reply_id: str,
    data: AnnotationReplyUpdate,
) -> dict[str, Any]:
    _annotation, reply = await _editable_reply(db, user, item_id, annotation_id, reply_id)
    new_version = await db.scalar(
        update(PdfAnnotationReply)
        .where(
            PdfAnnotationReply.id == reply_id,
            PdfAnnotationReply.version == data.version,
            PdfAnnotationReply.deleted_at.is_(None),
        )
        .values(
            body=data.body,
            version=PdfAnnotationReply.version + 1,
            updated_at=datetime.now(UTC),
        )
        .returning(PdfAnnotationReply.version)
    )
    if new_version is None:
        current_version = await db.scalar(
            select(PdfAnnotationReply.version).where(PdfAnnotationReply.id == reply_id)
        )
        raise VersionConflict(current_version)
    await db.refresh(reply)
    record_event(db, user.id, "annotation_reply.update", "pdf_annotation_reply", reply.id)
    await db.commit()
    author_name = await db.scalar(select(User.username).where(User.id == reply.author_id)) or ""
    return annotation_reply_json(
        reply,
        user.id,
        author_display_name=author_name,
        editable=True,
    )


async def delete_annotation_reply(
    db: AsyncSession,
    user: User,
    item_id: str,
    annotation_id: str,
    reply_id: str,
    version: int,
) -> None:
    _annotation, reply = await _editable_reply(db, user, item_id, annotation_id, reply_id)
    deleted_at = datetime.now(UTC)
    new_version = await db.scalar(
        update(PdfAnnotationReply)
        .where(
            PdfAnnotationReply.id == reply_id,
            PdfAnnotationReply.version == version,
            PdfAnnotationReply.deleted_at.is_(None),
        )
        .values(
            deleted_at=deleted_at,
            updated_at=deleted_at,
            version=PdfAnnotationReply.version + 1,
        )
        .returning(PdfAnnotationReply.version)
    )
    if new_version is None:
        current_version = await db.scalar(
            select(PdfAnnotationReply.version).where(PdfAnnotationReply.id == reply_id)
        )
        raise VersionConflict(current_version)
    record_event(db, user.id, "annotation_reply.delete", "pdf_annotation_reply", reply.id)
    await db.commit()


async def restore_annotation_reply(
    db: AsyncSession,
    user: User,
    item_id: str,
    annotation_id: str,
    reply_id: str,
    version: int,
) -> dict[str, Any]:
    locked_user, annotation = await require_visible_annotation_for_reply_mutation(
        db, user, item_id, annotation_id
    )
    reply = await db.scalar(
        select(PdfAnnotationReply).where(
            PdfAnnotationReply.id == reply_id,
            PdfAnnotationReply.annotation_id == annotation_id,
            PdfAnnotationReply.deleted_at.is_not(None),
        ).with_for_update()
    )
    if reply is None:
        raise ResourceUnavailable("annotation reply not found or cannot be restored")
    editable_ids = await editable_annotation_reply_ids(
        db, locked_user, [reply], {annotation.id: annotation}
    )
    if reply.id not in editable_ids:
        raise ResourceUnavailable("annotation reply not found or cannot be restored")
    restored_at = datetime.now(UTC)
    new_version = await db.scalar(
        update(PdfAnnotationReply)
        .where(
            PdfAnnotationReply.id == reply_id,
            PdfAnnotationReply.version == version,
            PdfAnnotationReply.deleted_at.is_not(None),
        )
        .values(
            deleted_at=None,
            updated_at=restored_at,
            version=PdfAnnotationReply.version + 1,
        )
        .returning(PdfAnnotationReply.version)
    )
    if new_version is None:
        current_version = await db.scalar(
            select(PdfAnnotationReply.version).where(PdfAnnotationReply.id == reply_id)
        )
        raise VersionConflict(current_version)
    await db.refresh(reply)
    record_event(db, user.id, "annotation_reply.restore", "pdf_annotation_reply", reply.id)
    await db.commit()
    author_name = await db.scalar(select(User.username).where(User.id == reply.author_id)) or ""
    return annotation_reply_json(
        reply,
        user.id,
        author_display_name=author_name,
        editable=True,
    )
