from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from quirebase.access.annotations import (
    editable_annotation_ids,
    editable_annotation_reply_ids,
    require_editable_annotation,
    require_restorable_annotation,
    require_visible_annotation_for_reply_mutation,
)
from quirebase.access.documents import require_revision
from quirebase.access.items import require_readable_item
from quirebase.access.workspaces import (
    Capability,
    require_project_context,
    require_workspace_capability,
    role_has_capability,
    visible_project_ids_query,
)
from quirebase.audit import record_event
from quirebase.core.errors import (
    DomainError,
    PermissionDenied,
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
    VersionConflict,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
)
from quirebase.core.timezones import as_utc
from quirebase.documents.schemas import ArrowPayload, InkPayload, LinePayload, TextMarkupPayload
from quirebase.models import (
    AnnotationScope,
    FileRevision,
    FileRevisionProcessingState,
    PdfAnnotation,
    PdfAnnotationObject,
    PdfAnnotationReply,
    Project,
    ProjectItem,
    ProjectState,
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


async def delete_project_item_annotations(
    db: AsyncSession, workspace_id: str, project_item_id: str
) -> None:
    """Remove a detached ProjectItem's annotations, replies and UUID identities.

    The caller holds an exclusive lock on the ProjectItem until commit. Locking
    its annotations also fences concurrent reply insertion through their FK.
    """
    annotation_ids = list(
        (
            await db.scalars(
                select(PdfAnnotation.id)
                .where(
                    PdfAnnotation.workspace_id == workspace_id,
                    PdfAnnotation.project_item_id == project_item_id,
                )
                .with_for_update()
            )
        ).all()
    )
    for start in range(0, len(annotation_ids), 500):
        batch = annotation_ids[start : start + 500]
        reply_ids = list(
            (
                await db.scalars(
                    select(PdfAnnotationReply.id).where(
                        PdfAnnotationReply.workspace_id == workspace_id,
                        PdfAnnotationReply.annotation_id.in_(batch),
                    )
                )
            ).all()
        )
        await db.execute(
            delete(PdfAnnotationReply).where(
                PdfAnnotationReply.workspace_id == workspace_id,
                PdfAnnotationReply.annotation_id.in_(batch),
            )
        )
        await db.execute(
            delete(PdfAnnotation).where(
                PdfAnnotation.workspace_id == workspace_id,
                PdfAnnotation.id.in_(batch),
            )
        )
        identity_ids = batch + reply_ids
        for identity_start in range(0, len(identity_ids), 500):
            identities = identity_ids[identity_start : identity_start + 500]
            await db.execute(
                delete(PdfAnnotationObject).where(PdfAnnotationObject.id.in_(identities))
            )


@dataclass(frozen=True)
class AnnotationReview:
    revisions: tuple[FileRevision, ...]
    annotations: tuple[dict[str, Any], ...]
    total: int


def annotation_json(
    record: PdfAnnotation,
    current_user_id: str,
    *,
    author_display_name: str,
    editable: bool,
    allowed_actions: list[str] | None = None,
    project_id: str | None = None,
    replies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "revision_id": record.file_revision_id,
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
        "allowed_actions": (
            allowed_actions
            if allowed_actions is not None
            else (["edit", "delete"] if editable else [])
        ),
        "hidden_at": as_utc(record.hidden_at).isoformat() if record.hidden_at else None,
        "archived_at": as_utc(record.archived_at).isoformat() if record.archived_at else None,
        "locked_at": as_utc(record.locked_at).isoformat() if record.locked_at else None,
        "moderated_by": record.moderated_by,
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
    workspace_id: str,
    revision_id: str,
    item_id: str,
    project_id: str | None = None,
) -> list[PdfAnnotation]:
    """Load the annotations visible to one user: own private ones, plus a project's."""
    workspace = await require_workspace_capability(
        db, user, workspace_id, Capability.workspace_read
    )
    moderator = role_has_capability(workspace.role, Capability.annotations_moderate)
    scopes = [
        and_(PdfAnnotation.scope == AnnotationScope.private, PdfAnnotation.author_id == user.id)
    ]
    if project_id:
        await require_project_context(db, user, workspace_id, project_id, Capability.workspace_read)
        project_item = await db.scalar(
            select(ProjectItem).where(
                ProjectItem.workspace_id == workspace_id,
                ProjectItem.project_id == project_id,
                ProjectItem.item_id == item_id,
            )
        )
        if project_item is None:
            raise ResourceUnavailable("ProjectItem not found")
        scopes.append(
            and_(
                PdfAnnotation.scope == AnnotationScope.project,
                PdfAnnotation.project_item_id == project_item.id,
            )
        )
    return list(
        (
            await db.scalars(
                select(PdfAnnotation)
                .where(
                    PdfAnnotation.file_revision_id == revision_id,
                    PdfAnnotation.workspace_id == workspace_id,
                    PdfAnnotation.deleted_at.is_(None),
                    *(
                        ()
                        if moderator
                        else (
                            PdfAnnotation.hidden_at.is_(None),
                            PdfAnnotation.archived_at.is_(None),
                        )
                    ),
                    or_(*scopes),
                )
                .order_by(PdfAnnotation.created_at, PdfAnnotation.id)
            )
        ).all()
    )


async def _annotation_views(
    db: AsyncSession, user: User, workspace_id: str, records: list[PdfAnnotation]
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
                    PdfAnnotationReply.workspace_id == workspace_id,
                    PdfAnnotationReply.deleted_at.is_(None),
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
    project_item_ids = {
        record.project_item_id for record in records if record.project_item_id is not None
    }
    project_rows = (
        await db.execute(
            select(ProjectItem.id, ProjectItem.project_id, Project.state)
            .join(Project, Project.id == ProjectItem.project_id)
            .where(
                ProjectItem.workspace_id == workspace_id,
                ProjectItem.id.in_(project_item_ids),
            )
        )
    ).all()
    project_ids_by_item: dict[str, str] = {row[0]: row[1] for row in project_rows}
    project_states_by_item: dict[str, ProjectState] = {row[0]: row[2] for row in project_rows}
    editable_ids = await editable_annotation_ids(db, user, workspace_id, records)
    try:
        await require_workspace_capability(db, user, workspace_id, Capability.annotations_moderate)
        can_moderate = True
    except (
        PermissionDenied,
        WorkspaceLifecycleError,
        WorkspaceMembershipRequired,
    ):
        can_moderate = False
    records_by_id = {record.id: record for record in records}
    editable_reply_ids = await editable_annotation_reply_ids(
        db, user, workspace_id, replies, records_by_id
    )
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
            allowed_actions=[
                *(["edit", "delete"] if record.id in editable_ids else []),
                *(
                    (
                        ["restore"]
                        if record.hidden_at is not None or record.archived_at is not None
                        else []
                    )
                    + (
                        ["hide", "archive"]
                        if record.hidden_at is None and record.archived_at is None
                        else []
                    )
                    + (["unlock"] if record.locked_at is not None else ["lock"])
                    if (
                        can_moderate
                        and record.scope is AnnotationScope.project
                        and record.project_item_id is not None
                        and project_states_by_item.get(record.project_item_id)
                        is ProjectState.active
                    )
                    else []
                ),
            ],
            project_id=(
                project_ids_by_item.get(record.project_item_id)
                if record.project_item_id is not None
                else None
            ),
            replies=replies_by_annotation[record.id],
        )
        for record in records
    ]


async def _editable_reply(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    reply_id: str,
) -> tuple[PdfAnnotation, PdfAnnotationReply]:
    locked_user, annotation = await require_visible_annotation_for_reply_mutation(
        db, user, workspace_id, item_id, annotation_id
    )
    reply = await db.scalar(
        select(PdfAnnotationReply)
        .where(
            PdfAnnotationReply.id == reply_id,
            PdfAnnotationReply.annotation_id == annotation_id,
            PdfAnnotationReply.workspace_id == workspace_id,
            PdfAnnotationReply.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if reply is None:
        raise ResourceUnavailable("annotation reply not found or cannot be edited")
    editable_ids = await editable_annotation_reply_ids(
        db, locked_user, workspace_id, [reply], {annotation.id: annotation}
    )
    if reply.id not in editable_ids:
        raise ResourceUnavailable("annotation reply not found or cannot be edited")
    return annotation, reply


async def list_document_annotations(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    revision_id: str,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    revision = await require_revision(db, user, workspace_id, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    records = await select_visible_annotations(
        db, user, workspace_id, revision_id, item_id, project_id
    )
    return await _annotation_views(db, user, workspace_id, records)


async def review_item_annotations(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    *,
    page: int,
    per_page: int,
    revision_id: str | None = None,
) -> AnnotationReview:
    """Load every Annotation scope visible to the caller for one Item in fixed queries."""
    await require_readable_item(db, user, workspace_id, item_id)
    workspace = await require_workspace_capability(
        db, user, workspace_id, Capability.workspace_read
    )
    moderator = role_has_capability(workspace.role, Capability.annotations_moderate)
    revisions = tuple(
        (
            await db.scalars(
                select(FileRevision)
                .where(
                    FileRevision.workspace_id == workspace_id,
                    FileRevision.item_id == item_id,
                )
                .order_by(FileRevision.created_at.desc(), FileRevision.id)
            )
        ).all()
    )
    if not revisions:
        return AnnotationReview(revisions=(), annotations=(), total=0)

    private_scope = and_(
        PdfAnnotation.scope == AnnotationScope.private,
        PdfAnnotation.author_id == user.id,
    )
    visible_project_ids = visible_project_ids_query(workspace)
    visible_project_item_ids = select(ProjectItem.id).where(
        ProjectItem.workspace_id == workspace_id,
        ProjectItem.item_id == item_id,
        ProjectItem.project_id.in_(visible_project_ids),
    )
    filters = [
        PdfAnnotation.file_revision_id.in_([revision.id for revision in revisions]),
        PdfAnnotation.workspace_id == workspace_id,
        PdfAnnotation.deleted_at.is_(None),
        *(
            ()
            if moderator
            else (
                PdfAnnotation.hidden_at.is_(None),
                PdfAnnotation.archived_at.is_(None),
            )
        ),
        or_(
            private_scope,
            and_(
                PdfAnnotation.scope == AnnotationScope.project,
                PdfAnnotation.project_item_id.in_(visible_project_item_ids),
            ),
        ),
    ]
    if revision_id is not None:
        filters.append(PdfAnnotation.file_revision_id == revision_id)
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
        annotations=tuple(await _annotation_views(db, user, workspace_id, records)),
        total=total,
    )


async def create_document_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    data: AnnotationCreate,
) -> dict[str, Any]:
    revision = await require_revision(db, user, workspace_id, data.revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    project_item: ProjectItem | None = None
    if data.scope is AnnotationScope.project:
        assert data.project_id is not None
        await require_project_context(
            db,
            user,
            workspace_id,
            data.project_id,
            Capability.annotations_project_write,
        )
        project_item = await db.scalar(
            select(ProjectItem).where(
                ProjectItem.workspace_id == workspace_id,
                ProjectItem.project_id == data.project_id,
                ProjectItem.item_id == item_id,
            )
        )
        if project_item is None:
            raise ResourceUnavailable("ProjectItem not found")
    else:
        await require_workspace_capability(
            db, user, workspace_id, Capability.annotations_private_write
        )
    validate_payload(data.page_index, data.payload, revision)
    object_id = str(data.id)
    record = PdfAnnotation(
        id=object_id,
        workspace_id=workspace_id,
        file_revision_id=data.revision_id,
        item_id=item_id,
        page_index=data.page_index,
        author_id=user.id,
        kind=data.kind,
        scope=data.scope,
        project_item_id=project_item.id if project_item else None,
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
    record_event(
        db,
        user.id,
        "annotation.create",
        "pdf_annotation",
        record.id,
        workspace_id=workspace_id,
        project_id=data.project_id,
        authorization_capability=(
            Capability.annotations_project_write.value
            if data.scope is AnnotationScope.project
            else Capability.annotations_private_write.value
        ),
    )
    await db.commit()
    return annotation_json(
        record,
        user.id,
        author_display_name=user.username,
        editable=True,
        project_id=data.project_id,
    )


async def update_document_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    data: AnnotationUpdate,
) -> dict[str, Any]:
    record = await require_editable_annotation(db, user, workspace_id, item_id, annotation_id)
    revision = await db.get(FileRevision, record.file_revision_id)
    if revision is None:
        raise ResourceNotFound("revision not found")
    project_item: ProjectItem | None = None
    if data.scope is AnnotationScope.project:
        assert data.project_id is not None
        await require_project_context(
            db,
            user,
            workspace_id,
            data.project_id,
            Capability.annotations_project_write,
        )
        project_item = await db.scalar(
            select(ProjectItem).where(
                ProjectItem.workspace_id == workspace_id,
                ProjectItem.project_id == data.project_id,
                ProjectItem.item_id == item_id,
            )
        )
        if project_item is None:
            raise ResourceUnavailable("ProjectItem not found")
    else:
        await require_workspace_capability(
            db, user, workspace_id, Capability.annotations_private_write
        )
    validate_payload(data.page_index, data.payload, revision)
    new_version = await db.scalar(
        update(PdfAnnotation)
        .where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.workspace_id == workspace_id,
            PdfAnnotation.version == data.version,
            PdfAnnotation.deleted_at.is_(None),
        )
        .values(
            page_index=data.page_index,
            kind=data.kind,
            scope=data.scope,
            project_item_id=project_item.id if project_item else None,
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
            select(PdfAnnotation.version).where(
                PdfAnnotation.id == annotation_id,
                PdfAnnotation.workspace_id == workspace_id,
            )
        )
        raise VersionConflict(current_version)
    await db.refresh(record)
    record_event(
        db,
        user.id,
        "annotation.update",
        "pdf_annotation",
        record.id,
        workspace_id=workspace_id,
        project_id=data.project_id,
        authorization_capability=(
            Capability.annotations_project_write.value
            if data.scope is AnnotationScope.project
            else Capability.annotations_private_write.value
        ),
    )
    await db.commit()
    return (await _annotation_views(db, user, workspace_id, [record]))[0]


async def delete_document_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    version: int,
) -> None:
    record = await require_editable_annotation(db, user, workspace_id, item_id, annotation_id)
    deleted_at = datetime.now(UTC)
    new_version = await db.scalar(
        update(PdfAnnotation)
        .where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.workspace_id == workspace_id,
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
            select(PdfAnnotation.version).where(
                PdfAnnotation.id == annotation_id,
                PdfAnnotation.workspace_id == workspace_id,
            )
        )
        raise VersionConflict(current_version)
    record_event(
        db,
        user.id,
        "annotation.delete",
        "pdf_annotation",
        record.id,
        workspace_id=workspace_id,
        authorization_capability=(
            Capability.annotations_project_write.value
            if record.scope is AnnotationScope.project
            else Capability.annotations_private_write.value
        ),
    )
    await db.commit()


async def restore_document_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    version: int,
) -> dict[str, Any]:
    record = await require_restorable_annotation(db, user, workspace_id, item_id, annotation_id)
    restored_at = datetime.now(UTC)
    new_version = await db.scalar(
        update(PdfAnnotation)
        .where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.workspace_id == workspace_id,
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
            select(PdfAnnotation.version).where(
                PdfAnnotation.id == annotation_id,
                PdfAnnotation.workspace_id == workspace_id,
            )
        )
        raise VersionConflict(current_version)
    await db.refresh(record)
    record_event(
        db,
        user.id,
        "annotation.restore",
        "pdf_annotation",
        record.id,
        workspace_id=workspace_id,
        authorization_capability=(
            Capability.annotations_project_write.value
            if record.scope is AnnotationScope.project
            else Capability.annotations_private_write.value
        ),
    )
    await db.commit()
    return (await _annotation_views(db, user, workspace_id, [record]))[0]


async def moderate_document_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    action: str,
    version: int,
) -> dict[str, Any]:
    """Change moderation state without rewriting authored content or attribution."""
    workspace = await require_workspace_capability(
        db, user, workspace_id, Capability.annotations_moderate
    )
    await require_readable_item(db, user, workspace_id, item_id)
    record = await db.scalar(
        select(PdfAnnotation).where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.workspace_id == workspace_id,
            PdfAnnotation.deleted_at.is_(None),
        )
    )
    revision = (
        await db.scalar(
            select(FileRevision).where(
                FileRevision.id == record.file_revision_id,
                FileRevision.workspace_id == workspace_id,
                FileRevision.item_id == item_id,
            )
        )
        if record is not None
        else None
    )
    if record is None or revision is None or record.scope is not AnnotationScope.project:
        raise ResourceUnavailable("Annotation not found")
    project_item = await db.scalar(
        select(ProjectItem).where(
            ProjectItem.id == record.project_item_id,
            ProjectItem.workspace_id == workspace_id,
            ProjectItem.item_id == item_id,
        )
    )
    if project_item is None:
        raise ResourceUnavailable("Annotation not found")
    project = await db.scalar(
        select(Project).where(
            Project.id == project_item.project_id,
            Project.workspace_id == workspace_id,
            Project.state != ProjectState.deleted,
        )
    )
    if project is None:
        raise ResourceUnavailable("Annotation Project not found")
    await require_project_context(
        db,
        user,
        workspace_id,
        project_item.project_id,
        Capability.annotations_moderate,
    )

    changed_at = datetime.now(UTC)
    values: dict[str, Any] = {
        "moderated_by": user.id,
        "updated_at": changed_at,
        "version": PdfAnnotation.version + 1,
    }
    if action == "hide":
        values["hidden_at"] = changed_at
    elif action == "archive":
        values["archived_at"] = changed_at
    elif action == "restore":
        values["hidden_at"] = None
        values["archived_at"] = None
    elif action == "lock":
        values["locked_at"] = changed_at
    elif action == "unlock":
        values["locked_at"] = None
    else:
        raise ValidationFailure("invalid Annotation moderation action")

    new_version = await db.scalar(
        update(PdfAnnotation)
        .where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.workspace_id == workspace_id,
            PdfAnnotation.version == version,
            PdfAnnotation.deleted_at.is_(None),
        )
        .values(**values)
        .returning(PdfAnnotation.version)
    )
    if new_version is None:
        current_version = await db.scalar(
            select(PdfAnnotation.version).where(
                PdfAnnotation.id == annotation_id,
                PdfAnnotation.workspace_id == workspace_id,
            )
        )
        raise VersionConflict(current_version)
    await db.refresh(record)
    record_event(
        db,
        user.id,
        f"annotation.moderate.{action}",
        "pdf_annotation",
        record.id,
        workspace_id=workspace_id,
        project_id=project_item.project_id,
        authorization_role=workspace.role.value,
        authorization_capability=Capability.annotations_moderate.value,
    )
    await db.commit()
    return (await _annotation_views(db, user, workspace_id, [record]))[0]


async def create_annotation_reply(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    data: AnnotationReplyCreate,
) -> dict[str, Any]:
    locked_user, annotation = await require_visible_annotation_for_reply_mutation(
        db, user, workspace_id, item_id, annotation_id
    )
    authorization_capability = (
        Capability.annotations_private_write
        if annotation.scope is AnnotationScope.private
        else Capability.annotations_project_write
    )
    object_id = str(data.id)
    record = PdfAnnotationReply(
        id=object_id,
        workspace_id=workspace_id,
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
        db,
        locked_user.id,
        "annotation_reply.create",
        "pdf_annotation_reply",
        record.id,
        workspace_id=workspace_id,
        authorization_capability=authorization_capability.value,
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
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    reply_id: str,
    data: AnnotationReplyUpdate,
) -> dict[str, Any]:
    annotation, reply = await _editable_reply(
        db, user, workspace_id, item_id, annotation_id, reply_id
    )
    authorization_capability = (
        Capability.annotations_private_write
        if annotation.scope is AnnotationScope.private
        else Capability.annotations_project_write
    )
    new_version = await db.scalar(
        update(PdfAnnotationReply)
        .where(
            PdfAnnotationReply.id == reply_id,
            PdfAnnotationReply.workspace_id == workspace_id,
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
            select(PdfAnnotationReply.version).where(
                PdfAnnotationReply.id == reply_id,
                PdfAnnotationReply.workspace_id == workspace_id,
            )
        )
        raise VersionConflict(current_version)
    await db.refresh(reply)
    record_event(
        db,
        user.id,
        "annotation_reply.update",
        "pdf_annotation_reply",
        reply.id,
        workspace_id=workspace_id,
        authorization_capability=authorization_capability.value,
    )
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
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    reply_id: str,
    version: int,
) -> None:
    annotation, reply = await _editable_reply(
        db, user, workspace_id, item_id, annotation_id, reply_id
    )
    authorization_capability = (
        Capability.annotations_private_write
        if annotation.scope is AnnotationScope.private
        else Capability.annotations_project_write
    )
    deleted_at = datetime.now(UTC)
    new_version = await db.scalar(
        update(PdfAnnotationReply)
        .where(
            PdfAnnotationReply.id == reply_id,
            PdfAnnotationReply.workspace_id == workspace_id,
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
            select(PdfAnnotationReply.version).where(
                PdfAnnotationReply.id == reply_id,
                PdfAnnotationReply.workspace_id == workspace_id,
            )
        )
        raise VersionConflict(current_version)
    record_event(
        db,
        user.id,
        "annotation_reply.delete",
        "pdf_annotation_reply",
        reply.id,
        workspace_id=workspace_id,
        authorization_capability=authorization_capability.value,
    )
    await db.commit()


async def restore_annotation_reply(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    reply_id: str,
    version: int,
) -> dict[str, Any]:
    locked_user, annotation = await require_visible_annotation_for_reply_mutation(
        db, user, workspace_id, item_id, annotation_id
    )
    authorization_capability = (
        Capability.annotations_private_write
        if annotation.scope is AnnotationScope.private
        else Capability.annotations_project_write
    )
    reply = await db.scalar(
        select(PdfAnnotationReply)
        .where(
            PdfAnnotationReply.id == reply_id,
            PdfAnnotationReply.annotation_id == annotation_id,
            PdfAnnotationReply.workspace_id == workspace_id,
            PdfAnnotationReply.deleted_at.is_not(None),
        )
        .with_for_update()
    )
    if reply is None:
        raise ResourceUnavailable("annotation reply not found or cannot be restored")
    editable_ids = await editable_annotation_reply_ids(
        db, locked_user, workspace_id, [reply], {annotation.id: annotation}
    )
    if reply.id not in editable_ids:
        raise ResourceUnavailable("annotation reply not found or cannot be restored")
    restored_at = datetime.now(UTC)
    new_version = await db.scalar(
        update(PdfAnnotationReply)
        .where(
            PdfAnnotationReply.id == reply_id,
            PdfAnnotationReply.workspace_id == workspace_id,
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
            select(PdfAnnotationReply.version).where(
                PdfAnnotationReply.id == reply_id,
                PdfAnnotationReply.workspace_id == workspace_id,
            )
        )
        raise VersionConflict(current_version)
    await db.refresh(reply)
    record_event(
        db,
        user.id,
        "annotation_reply.restore",
        "pdf_annotation_reply",
        reply.id,
        workspace_id=workspace_id,
        authorization_capability=authorization_capability.value,
    )
    await db.commit()
    author_name = await db.scalar(select(User.username).where(User.id == reply.author_id)) or ""
    return annotation_reply_json(
        reply,
        user.id,
        author_display_name=author_name,
        editable=True,
    )
