from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from quirebase.access.annotations import (
    editable_annotation_ids,
    editable_annotation_reply_ids,
    require_deletable_annotation,
    require_editable_annotation,
    require_visible_annotation_for_reply_mutation,
)
from quirebase.access.documents import require_revision
from quirebase.access.items import require_readable_item
from quirebase.access.projects import project_member
from quirebase.audit import record_event
from quirebase.core.errors import (
    DomainError,
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
    VersionConflict,
)
from quirebase.core.timezones import as_utc
from quirebase.documents.schemas import ArrowPayload, InkPayload, LinePayload, TextMarkupPayload
from quirebase.models import (
    AnnotationScope,
    FileRevision,
    FileRevisionProcessingState,
    ItemFileRevision,
    PdfAnnotation,
    PdfAnnotationReply,
    ProjectItem,
    ProjectMember,
    ProjectRole,
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


@dataclass(frozen=True)
class AnnotationReview:
    revisions: tuple[FileRevision, ...]
    annotations: tuple[dict[str, Any], ...]
    total: int


def annotation_json(
    record: PdfAnnotation,
    current_user_id: str,
    *,
    revision_id: str,
    project_id: str | None,
    author_display_name: str,
    editable: bool,
    replies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "revision_id": revision_id,
        "page_index": record.page_index,
        "kind": record.kind,
        "scope": record.scope,
        "project_id": project_id,
        "body": record.body,
        "selected_text": record.selected_text,
        "payload": record.payload,
        "version": record.version,
        "author_display_name": author_display_name,
        "mine": record.author_id == current_user_id,
        "editable": editable,
        "created_at": as_utc(record.created_at).isoformat(),
        "updated_at": as_utc(record.updated_at).isoformat(),
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
        "created_at": as_utc(record.created_at).isoformat(),
        "updated_at": as_utc(record.updated_at).isoformat(),
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
            or await db.scalar(
                select(ProjectItem.id).where(
                    ProjectItem.project_id == project_id, ProjectItem.item_id == item_id
                )
            )
            is None
        ):
            raise ResourceUnavailable("project membership or project item not found")
        scopes.append(
            and_(
                PdfAnnotation.scope == AnnotationScope.project,
                PdfAnnotation.project_item_id.in_(
                    select(ProjectItem.id).where(
                        ProjectItem.project_id == project_id, ProjectItem.item_id == item_id
                    )
                ),
            )
        )
    return list(
        (
            await db.scalars(
                select(PdfAnnotation)
                .where(
                    PdfAnnotation.item_file_revision_id.in_(
                        select(ItemFileRevision.id).where(
                            ItemFileRevision.file_revision_id == revision_id,
                            ItemFileRevision.item_id == item_id,
                        )
                    ),
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
    revision_rows = (
        await db.execute(
            select(ItemFileRevision.id, ItemFileRevision.file_revision_id).where(
                ItemFileRevision.id.in_({record.item_file_revision_id for record in records})
            )
        )
    ).all()
    revision_ids = {row[0]: row[1] for row in revision_rows}
    project_item_ids = {
        record.project_item_id for record in records if record.project_item_id is not None
    }
    project_rows = (
        (
            await db.execute(
                select(ProjectItem.id, ProjectItem.project_id).where(
                    ProjectItem.id.in_(project_item_ids)
                )
            )
        ).all()
        if project_item_ids
        else []
    )
    project_ids = {row[0]: row[1] for row in project_rows}
    replies = list(
        (
            await db.scalars(
                select(PdfAnnotationReply)
                .where(
                    PdfAnnotationReply.annotation_id.in_(annotation_ids),
                )
                .order_by(PdfAnnotationReply.created_at, PdfAnnotationReply.id)
            )
        ).all()
    )
    author_ids = {record.author_id for record in records} | {reply.author_id for reply in replies}
    author_rows = (
        await db.execute(select(User.id, User.username).where(User.id.in_(author_ids)))
    ).all()
    authors: dict[str, str] = {row[0]: row[1] for row in author_rows}
    editable_ids = editable_annotation_ids(user, records)
    editable_reply_ids = editable_annotation_reply_ids(user, replies)
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
            revision_id=revision_ids[record.item_file_revision_id],
            project_id=project_ids.get(record.project_item_id),
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
        select(PdfAnnotationReply)
        .where(
            PdfAnnotationReply.id == reply_id,
            PdfAnnotationReply.annotation_id == annotation_id,
        )
        .with_for_update()
    )
    if reply is None:
        raise ResourceUnavailable("annotation reply not found or cannot be edited")
    editable_ids = editable_annotation_reply_ids(locked_user, [reply])
    if reply.id not in editable_ids:
        raise ResourceUnavailable("annotation reply not found or cannot be edited")
    return annotation, reply


async def _deletable_reply(
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
        select(PdfAnnotationReply)
        .where(
            PdfAnnotationReply.id == reply_id,
            PdfAnnotationReply.annotation_id == annotation_id,
        )
        .with_for_update()
    )
    if reply is None:
        raise ResourceUnavailable("annotation reply not found or cannot be deleted")
    allowed = (
        reply.author_id == locked_user.id or locked_user.role == SystemRole.administrator.value
    )
    if not allowed and annotation.project_item_id is not None:
        allowed = (
            await db.scalar(
                select(ProjectMember.project_id)
                .join(ProjectItem, ProjectItem.project_id == ProjectMember.project_id)
                .where(
                    ProjectItem.id == annotation.project_item_id,
                    ProjectMember.user_id == locked_user.id,
                    ProjectMember.role == ProjectRole.admin,
                )
                .limit(1)
            )
            is not None
        )
    if not allowed:
        raise ResourceUnavailable("annotation reply not found or cannot be deleted")
    return annotation, reply


async def list_document_annotations(
    db: AsyncSession,
    user: User,
    item_id: str,
    revision_id: str,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    await require_revision(db, user, revision_id)
    if (
        await db.scalar(
            select(ItemFileRevision.id).where(
                ItemFileRevision.file_revision_id == revision_id,
                ItemFileRevision.item_id == item_id,
            )
        )
        is None
    ):
        raise ResourceNotFound("revision not found for item")
    records = await select_visible_annotations(db, user, revision_id, item_id, project_id)
    return await _annotation_views(db, user, records)


async def review_item_annotations(
    db: AsyncSession,
    user: User,
    item_id: str,
    *,
    page: int,
    per_page: int,
    revision_id: str | None = None,
) -> AnnotationReview:
    """Load every Annotation scope visible to the caller for one Item in fixed queries."""
    await require_readable_item(db, user, item_id)
    revisions = tuple(
        (
            await db.scalars(
                select(FileRevision)
                .join(ItemFileRevision, ItemFileRevision.file_revision_id == FileRevision.id)
                .where(ItemFileRevision.item_id == item_id)
                .order_by(FileRevision.created_at.desc(), FileRevision.id)
            )
        ).all()
    )
    if not revisions:
        return AnnotationReview(revisions=(), annotations=(), total=0)

    item_project_ids = select(ProjectItem.project_id).where(ProjectItem.item_id == item_id)
    if user.role == SystemRole.administrator.value:
        private_scope = PdfAnnotation.scope == AnnotationScope.private
        visible_project_ids = item_project_ids
    else:
        private_scope = and_(
            PdfAnnotation.scope == AnnotationScope.private,
            PdfAnnotation.author_id == user.id,
        )
        visible_project_ids = select(ProjectMember.project_id).where(
            ProjectMember.user_id == user.id,
            ProjectMember.project_id.in_(item_project_ids),
        )
    filters = [
        PdfAnnotation.item_file_revision_id.in_(
            list(
                await db.scalars(
                    select(ItemFileRevision.id).where(ItemFileRevision.item_id == item_id)
                )
            )
        ),
        or_(
            private_scope,
            and_(
                PdfAnnotation.scope == AnnotationScope.project,
                PdfAnnotation.project_item_id.in_(
                    select(ProjectItem.id).where(
                        ProjectItem.project_id.in_(visible_project_ids),
                        ProjectItem.item_id == item_id,
                    )
                ),
            ),
        ),
    ]
    if revision_id is not None:
        filters.append(
            PdfAnnotation.item_file_revision_id.in_(
                select(ItemFileRevision.id).where(
                    ItemFileRevision.file_revision_id == revision_id,
                    ItemFileRevision.item_id == item_id,
                )
            )
        )
    total = int(
        await db.scalar(select(func.count()).select_from(PdfAnnotation).where(*filters)) or 0
    )
    records = list(
        (
            await db.scalars(
                select(PdfAnnotation)
                .where(*filters)
                .order_by(PdfAnnotation.updated_at.desc(), PdfAnnotation.id)
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
    )
    return AnnotationReview(
        revisions=revisions,
        annotations=tuple(await _annotation_views(db, user, records)),
        total=total,
    )


async def create_document_annotation(
    db: AsyncSession,
    user: User,
    item_id: str,
    data: AnnotationCreate,
) -> dict[str, Any]:
    revision = await require_revision(db, user, data.revision_id)
    if (
        await db.scalar(
            select(ItemFileRevision.id).where(
                ItemFileRevision.file_revision_id == data.revision_id,
                ItemFileRevision.item_id == item_id,
            )
        )
        is None
    ):
        raise ResourceNotFound("revision not found for item")
    if data.scope is AnnotationScope.project and (
        await project_member(db, user, data.project_id) is None
        or await db.scalar(
            select(ProjectItem.id).where(
                ProjectItem.project_id == data.project_id, ProjectItem.item_id == item_id
            )
        )
        is None
    ):
        raise ResourceUnavailable("project membership or project item not found")
    validate_payload(data.page_index, data.payload, revision)
    object_id = str(data.id)
    record = PdfAnnotation(
        id=object_id,
        item_file_revision_id=(
            await db.scalar(
                select(ItemFileRevision.id).where(
                    ItemFileRevision.file_revision_id == data.revision_id,
                    ItemFileRevision.item_id == item_id,
                )
            )
        ),
        item_id=item_id,
        page_index=data.page_index,
        author_id=user.id,
        kind=data.kind,
        scope=data.scope,
        project_item_id=(
            await db.scalar(
                select(ProjectItem.id).where(
                    ProjectItem.project_id == data.project_id, ProjectItem.item_id == item_id
                )
            )
        )
        if data.project_id
        else None,
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
        revision_id=data.revision_id,
        project_id=data.project_id,
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
    revision = await db.get(
        FileRevision,
        (
            await db.scalar(
                select(ItemFileRevision.file_revision_id).where(
                    ItemFileRevision.id == record.item_file_revision_id
                )
            )
        ),
    )
    if revision is None:
        raise ResourceNotFound("revision not found")
    current_project_id = (
        await db.scalar(
            select(ProjectItem.project_id).where(ProjectItem.id == record.project_item_id)
        )
        if record.project_item_id is not None
        else None
    )
    if current_project_id != data.project_id:
        raise ValidationFailure("annotation project scope cannot change")
    if data.scope is AnnotationScope.project and (
        await db.scalar(
            select(ProjectItem.id).where(
                ProjectItem.project_id == data.project_id, ProjectItem.item_id == item_id
            )
        )
        is None
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
        )
        .values(
            page_index=data.page_index,
            kind=data.kind,
            scope=data.scope,
            project_item_id=(
                await db.scalar(
                    select(ProjectItem.id).where(
                        ProjectItem.project_id == data.project_id, ProjectItem.item_id == item_id
                    )
                )
            )
            if data.project_id
            else None,
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
    record = await require_deletable_annotation(db, user, item_id, annotation_id)
    if record.version != version:
        raise VersionConflict(record.version)
    await db.delete(record)
    record_event(db, user.id, "annotation.delete", "pdf_annotation", record.id)
    await db.commit()


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
    record_event(db, locked_user.id, "annotation_reply.create", "pdf_annotation_reply", record.id)
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
    _annotation, reply = await _deletable_reply(db, user, item_id, annotation_id, reply_id)
    if reply.version != version:
        raise VersionConflict(reply.version)
    await db.delete(reply)
    record_event(db, user.id, "annotation_reply.delete", "pdf_annotation_reply", reply.id)
    await db.commit()
