from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from quirebase.access.annotations import (
    annotation_decisions,
    annotation_moderation_action,
    editable_annotation_ids,
    editable_annotation_reply_ids,
    require_deletable_annotation,
    require_editable_annotation,
    require_restorable_annotation,
    require_visible_annotation_for_reply_mutation,
    visible_annotation_scope_predicate,
)
from quirebase.access.documents import require_revision
from quirebase.access.items import require_readable_item
from quirebase.access.workspaces import (
    ResourceAction,
    action_allowed,
    require_project_context,
    require_workspace_action,
    resolve_workspace_context,
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


async def _lock_annotation_project_item(
    db: AsyncSession, workspace_id: str, project_id: str, item_id: str
) -> ProjectItem:
    """Fence ProjectItem detachment while an Annotation write binds to it."""
    project_item = await db.scalar(
        select(ProjectItem)
        .where(
            ProjectItem.workspace_id == workspace_id,
            ProjectItem.project_id == project_id,
            ProjectItem.item_id == item_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update(read=True)
    )
    if project_item is None:
        raise ResourceUnavailable("ProjectItem not found")
    return project_item


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
class AnnotationPage:
    revisions: tuple[FileRevision, ...]
    projects: tuple[Project, ...]
    annotations: tuple[dict[str, Any], ...]
    total: int
    next_cursor: str | None = None


def annotation_json(
    record: PdfAnnotation,
    current_user_id: str,
    *,
    author_display_name: str,
    editable: bool,
    authorization_resource_actions: list[str],
    revision_name: str,
    project_id: str | None = None,
    project_name: str | None = None,
    replies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "revision_id": record.file_revision_id,
        "revision_name": revision_name,
        "page_index": record.page_index,
        "kind": record.kind,
        "scope": record.scope,
        "project_id": project_id,
        "project_name": project_name,
        "body": record.body,
        "selected_text": record.selected_text,
        "payload": record.payload,
        "version": record.version,
        "author_display_name": author_display_name,
        "mine": record.author_id == current_user_id,
        "editable": editable,
        "authorization": {"allowed": authorization_resource_actions},
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
    """Load exportable annotations: own private ones, plus a project's.

    Exports exclude hidden and archived annotations even for moderators.
    """
    workspace = await require_workspace_action(
        db, user, workspace_id, ResourceAction.workspace_read
    )
    project_item_ids = None
    if project_id:
        await require_project_context(
            db, user, workspace_id, project_id, ResourceAction.workspace_read
        )
        project_item = await db.scalar(
            select(ProjectItem).where(
                ProjectItem.workspace_id == workspace_id,
                ProjectItem.project_id == project_id,
                ProjectItem.item_id == item_id,
            )
        )
        if project_item is None:
            raise ResourceUnavailable("ProjectItem not found")
        project_item_ids = (project_item.id,)
    return list(
        (
            await db.scalars(
                select(PdfAnnotation)
                .where(
                    PdfAnnotation.file_revision_id == revision_id,
                    PdfAnnotation.workspace_id == workspace_id,
                    PdfAnnotation.deleted_at.is_(None),
                    PdfAnnotation.hidden_at.is_(None),
                    PdfAnnotation.archived_at.is_(None),
                    visible_annotation_scope_predicate(
                        workspace,
                        project_item_ids=project_item_ids,
                        include_project=project_id is not None,
                    ),
                )
                .order_by(PdfAnnotation.created_at, PdfAnnotation.id)
            )
        ).all()
    )


async def _annotation_views(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    records: list[PdfAnnotation],
    *,
    revision_names: dict[str, str] | None = None,
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
            select(ProjectItem.id, ProjectItem.project_id, Project.state, Project.name)
            .join(Project, Project.id == ProjectItem.project_id)
            .where(
                ProjectItem.workspace_id == workspace_id,
                ProjectItem.id.in_(project_item_ids),
            )
        )
    ).all()
    project_ids_by_item: dict[str, str] = {row[0]: row[1] for row in project_rows}
    project_states_by_item: dict[str, ProjectState] = {row[0]: row[2] for row in project_rows}
    project_names_by_item: dict[str, str] = {row[0]: row[3] for row in project_rows}
    if revision_names is None:
        revision_names = dict(
            (
                await db.execute(
                    select(FileRevision.id, FileRevision.original_name).where(
                        FileRevision.id.in_({record.file_revision_id for record in records}),
                        FileRevision.workspace_id == workspace_id,
                    )
                )
            )
            .tuples()
            .all()
        )
    editable_ids = await editable_annotation_ids(db, user, workspace_id, records)
    workspace = await resolve_workspace_context(db, user, workspace_id)
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
    views: list[dict[str, Any]] = []
    for record in records:
        revision_name = revision_names.get(record.file_revision_id)
        if revision_name is None:
            raise ResourceNotFound("revision not found")
        authorization_resource_actions = [
            action.value
            for action in annotation_decisions(
                workspace,
                record,
                editable=record.id in editable_ids,
                project_active=(
                    record.project_item_id is not None
                    and project_states_by_item.get(record.project_item_id) is ProjectState.active
                ),
            )
        ]

        views.append(
            annotation_json(
                record,
                user.id,
                author_display_name=authors.get(record.author_id, ""),
                editable=record.id in editable_ids,
                authorization_resource_actions=authorization_resource_actions,
                revision_name=revision_name,
                project_id=(
                    project_ids_by_item.get(record.project_item_id)
                    if record.project_item_id is not None
                    else None
                ),
                project_name=project_names_by_item.get(record.project_item_id or ""),
                replies=replies_by_annotation[record.id],
            )
        )
    return views


async def _editable_reply(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    reply_id: str,
    *,
    action: str,
) -> tuple[PdfAnnotation, PdfAnnotationReply]:
    _locked_user, annotation = await require_visible_annotation_for_reply_mutation(
        db, user, workspace_id, item_id, annotation_id, action=action
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
    resource_action = ResourceAction(
        f"{'private' if annotation.scope is AnnotationScope.private else 'project'}"
        f"_annotation_reply.{action}"
    )
    relation = "own" if reply.author_id == user.id else "other"
    try:
        await _require_reply_action(
            db,
            user,
            workspace_id,
            annotation,
            resource_action,
            relation=relation,
        )
    except PermissionDenied as error:
        raise ResourceUnavailable("annotation reply not found or cannot be edited") from error
    return annotation, reply


async def _require_reply_action(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    annotation: PdfAnnotation,
    resource_action: ResourceAction,
    *,
    relation: str,
) -> None:
    if annotation.scope is AnnotationScope.private:
        await require_workspace_action(
            db,
            user,
            workspace_id,
            resource_action,
            relation=relation,
        )
        return
    project_item = await db.scalar(
        select(ProjectItem).where(
            ProjectItem.id == annotation.project_item_id,
            ProjectItem.workspace_id == workspace_id,
        )
    )
    if project_item is None:
        raise ResourceUnavailable("Annotation not found")
    await require_project_context(
        db,
        user,
        workspace_id,
        project_item.project_id,
        resource_action,
        relation=relation,
    )


async def list_document_annotations(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    revision_id: str | None = None,
    *,
    page: int = 1,
    per_page: int = 50,
    scope: AnnotationScope | None = None,
    project_ids: tuple[str, ...] | None = None,
    pagination: Literal["page", "cursor"] = "page",
    cursor: str | None = None,
) -> AnnotationPage:
    """List visible Item annotations, with independent revision and source filters."""
    if page < 1 or not 1 <= per_page <= 100:
        raise ValidationFailure("Invalid annotation pagination")
    if (
        pagination not in ("page", "cursor")
        or (pagination == "page" and cursor is not None)
        or (pagination == "cursor" and page != 1)
    ):
        raise ValidationFailure("Invalid annotation pagination mode")
    await require_readable_item(db, user, workspace_id, item_id)
    workspace = await require_workspace_action(
        db, user, workspace_id, ResourceAction.workspace_read
    )
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
    if revision_id is not None and revision_id not in {revision.id for revision in revisions}:
        raise ResourceNotFound("revision not found for item")
    projects = tuple(
        (
            await db.scalars(
                select(Project)
                .join(ProjectItem, ProjectItem.project_id == Project.id)
                .where(
                    ProjectItem.workspace_id == workspace_id,
                    ProjectItem.item_id == item_id,
                    Project.id.in_(visible_project_ids_query(workspace)),
                )
                .order_by(Project.name, Project.id)
            )
        ).all()
    )
    visible_project_ids = {project.id for project in projects}
    if project_ids is not None and not set(project_ids) <= visible_project_ids:
        raise ResourceUnavailable("ProjectItem not found")
    # Source choices can outlive a concurrent participation change. Count and
    # data queries must re-evaluate Project visibility in their own SQL statement.
    project_item_ids = select(ProjectItem.id).where(
        ProjectItem.workspace_id == workspace_id,
        ProjectItem.item_id == item_id,
        ProjectItem.project_id.in_(visible_project_ids_query(workspace)),
        ProjectItem.project_id.in_(project_ids if project_ids is not None else visible_project_ids),
    )
    moderator = action_allowed(workspace, ResourceAction.project_annotation_review)
    filters = [
        PdfAnnotation.item_id == item_id,
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
        visible_annotation_scope_predicate(
            workspace,
            project_item_ids=project_item_ids,
            include_private=scope is not AnnotationScope.project,
            include_project=scope is not AnnotationScope.private,
        ),
    ]
    if revision_id is not None:
        filters.append(PdfAnnotation.file_revision_id == revision_id)
    total = int(
        await db.scalar(select(func.count()).select_from(PdfAnnotation).where(*filters)) or 0
    )
    # Read names with their annotations: a later statement under READ COMMITTED
    # could see the revision's cascade deletion after these ORM objects are loaded.
    query = select(PdfAnnotation, FileRevision.original_name).join(FileRevision).where(*filters)
    if pagination == "cursor":
        # IDs never move when content is edited, and a deleted cursor row need
        # not exist for the next page to remain reachable.
        if cursor is not None:
            query = query.where(PdfAnnotation.id > cursor)
        query = query.order_by(PdfAnnotation.id).limit(per_page + 1)
    else:
        query = (
            query
            .order_by(PdfAnnotation.updated_at.desc(), PdfAnnotation.id)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    rows = (await db.execute(query)).tuples().all()
    records = [record for record, _name in rows]
    revision_names = {record.file_revision_id: name for record, name in rows}
    next_cursor = (
        records[per_page - 1].id if pagination == "cursor" and len(records) > per_page else None
    )
    records = records[:per_page]
    return AnnotationPage(
        revisions=revisions,
        projects=projects,
        annotations=tuple(
            await _annotation_views(db, user, workspace_id, records, revision_names=revision_names)
        ),
        total=total,
        next_cursor=next_cursor,
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
            ResourceAction.project_annotation_create,
            relation="own",
        )
        project_item = await _lock_annotation_project_item(
            db,
            workspace_id,
            data.project_id,
            item_id,
        )
    else:
        await require_workspace_action(
            db,
            user,
            workspace_id,
            ResourceAction.private_annotation_create,
            relation="own",
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
        authorization_resource_action=(
            ResourceAction.project_annotation_create.value
            if data.scope is AnnotationScope.project
            else ResourceAction.private_annotation_create.value
        ),
    )
    await db.commit()
    return (await _annotation_views(db, user, workspace_id, [record]))[0]


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
            ResourceAction.project_annotation_update,
            relation="own",
        )
        project_item = await _lock_annotation_project_item(
            db,
            workspace_id,
            data.project_id,
            item_id,
        )
    else:
        await require_workspace_action(
            db,
            user,
            workspace_id,
            ResourceAction.private_annotation_update,
            relation="own",
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
        authorization_resource_action=(
            ResourceAction.project_annotation_update.value
            if data.scope is AnnotationScope.project
            else ResourceAction.private_annotation_update.value
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
    record = await require_deletable_annotation(db, user, workspace_id, item_id, annotation_id)
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
            deleted_by_moderation=False,
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
        authorization_resource_action=(
            ResourceAction.project_annotation_delete.value
            if record.scope is AnnotationScope.project
            else ResourceAction.private_annotation_delete.value
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
            PdfAnnotation.deleted_by_moderation.is_(False),
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
        authorization_resource_action=(
            ResourceAction.project_annotation_restore.value
            if record.scope is AnnotationScope.project
            else ResourceAction.private_annotation_restore.value
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
    moderation_actions = {"hide", "archive", "restore", "lock", "unlock", "delete"}
    if action not in moderation_actions:
        raise ValidationFailure("invalid Annotation moderation action")
    workspace = await require_workspace_action(
        db, user, workspace_id, ResourceAction.workspace_read
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
    relation = "own" if record.author_id == workspace.actor_id else "other"
    if relation == "own":
        raise ValidationFailure("authors cannot moderate their own Annotation")
    moderation_action = annotation_moderation_action(action)
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
    project_context = await require_project_context(
        db,
        user,
        workspace_id,
        project_item.project_id,
        moderation_action,
        relation=relation,
    )
    workspace = project_context.workspace

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
    elif action == "delete":
        values["deleted_at"] = changed_at
        values["deleted_by_moderation"] = True
    else:  # Pydantic and the guard above keep this branch unreachable.
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
        detail={"author_id": record.author_id} if action == "delete" else None,
        workspace_id=workspace_id,
        project_id=project_item.project_id,
        authorization_role=workspace.role.value,
        authorization_resource_action=moderation_action.value,
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
        db, user, workspace_id, item_id, annotation_id, action="create"
    )
    context = await resolve_workspace_context(db, locked_user, workspace_id)
    resource = (
        "private_annotation_reply"
        if annotation.scope is AnnotationScope.private
        else "project_annotation_reply"
    )
    relation = "own" if annotation.author_id == context.actor_id else "other"
    resource_action = ResourceAction(f"{resource}.create")
    await _require_reply_action(
        db,
        locked_user,
        workspace_id,
        annotation,
        resource_action,
        relation=relation,
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
        authorization_resource_action=resource_action.value,
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
        db,
        user,
        workspace_id,
        item_id,
        annotation_id,
        reply_id,
        action="update",
    )
    resource_action = ResourceAction(
        "private_annotation_reply.update"
        if annotation.scope is AnnotationScope.private
        else "project_annotation_reply.update"
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
        authorization_resource_action=resource_action.value,
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
        db,
        user,
        workspace_id,
        item_id,
        annotation_id,
        reply_id,
        action="delete",
    )
    resource_action = ResourceAction(
        "private_annotation_reply.delete"
        if annotation.scope is AnnotationScope.private
        else "project_annotation_reply.delete"
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
        authorization_resource_action=resource_action.value,
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
        db, user, workspace_id, item_id, annotation_id, action="restore"
    )
    resource_action = ResourceAction(
        "private_annotation_reply.restore"
        if annotation.scope is AnnotationScope.private
        else "project_annotation_reply.restore"
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
    relation = "own" if reply.author_id == locked_user.id else "other"
    try:
        await _require_reply_action(
            db,
            locked_user,
            workspace_id,
            annotation,
            resource_action,
            relation=relation,
        )
    except PermissionDenied as error:
        raise ResourceUnavailable("annotation reply not found or cannot be restored") from error
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
        authorization_resource_action=resource_action.value,
    )
    await db.commit()
    author_name = await db.scalar(select(User.username).where(User.id == reply.author_id)) or ""
    return annotation_reply_json(
        reply,
        user.id,
        author_display_name=author_name,
        editable=True,
    )
