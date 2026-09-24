from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.access.items import require_readable_item
from quirebase.access.workspaces import (
    Capability,
    require_project_context,
    require_workspace_capability,
)
from quirebase.core.errors import (
    PermissionDenied,
    ResourceUnavailable,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
)
from quirebase.models import (
    AnnotationScope,
    FileRevision,
    PdfAnnotation,
    PdfAnnotationReply,
    ProjectItem,
    User,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def can_edit_annotation(
    db: AsyncSession, user: User, workspace_id: str, annotation: PdfAnnotation
) -> bool:
    try:
        await _require_annotation_write(db, user, workspace_id, annotation)
    except (
        PermissionDenied,
        ResourceUnavailable,
        WorkspaceLifecycleError,
        WorkspaceMembershipRequired,
    ):
        return False
    return True


async def _require_annotation_project_write(
    db: AsyncSession, user: User, workspace_id: str, annotation: PdfAnnotation
) -> None:
    project_item = await db.scalar(
        select(ProjectItem).where(
            ProjectItem.id == annotation.project_item_id,
            ProjectItem.workspace_id == workspace_id,
        )
    )
    if project_item is None:
        raise ResourceUnavailable("Annotation Project not found")
    await require_project_context(
        db,
        user,
        workspace_id,
        project_item.project_id,
        Capability.annotations_project_write,
    )


async def _require_annotation_write(
    db: AsyncSession, user: User, workspace_id: str, annotation: PdfAnnotation
) -> None:
    if (
        annotation.workspace_id != workspace_id
        or annotation.author_id != user.id
        or annotation.hidden_at is not None
        or annotation.archived_at is not None
        or annotation.locked_at is not None
    ):
        raise ResourceUnavailable("Annotation not found")
    if annotation.scope is AnnotationScope.private:
        await require_workspace_capability(
            db, user, workspace_id, Capability.annotations_private_write
        )
    else:
        await _require_annotation_project_write(db, user, workspace_id, annotation)


async def editable_annotation_ids(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    annotations: list[PdfAnnotation],
) -> set[str]:
    return {
        annotation.id
        for annotation in annotations
        if await can_edit_annotation(db, user, workspace_id, annotation)
    }


async def editable_annotation_reply_ids(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    replies: list[PdfAnnotationReply],
    annotations: dict[str, PdfAnnotation],
) -> set[str]:
    if not replies:
        return set()
    editable: set[str] = set()
    writable_project_items: dict[str, bool] = {}
    private_write: bool | None = None
    for reply in replies:
        annotation = annotations.get(reply.annotation_id)
        if (
            reply.workspace_id != workspace_id
            or reply.author_id != user.id
            or annotation is None
            or annotation.hidden_at is not None
            or annotation.archived_at is not None
            or annotation.locked_at is not None
        ):
            continue
        if annotation.scope is AnnotationScope.private:
            if annotation.author_id != user.id:
                continue
            if private_write is None:
                try:
                    await require_workspace_capability(
                        db, user, workspace_id, Capability.annotations_private_write
                    )
                    private_write = True
                except (PermissionDenied, WorkspaceLifecycleError, WorkspaceMembershipRequired):
                    private_write = False
            if private_write:
                editable.add(reply.id)
            continue
        if annotation.project_item_id is None:
            continue
        project_item_id = annotation.project_item_id
        if project_item_id not in writable_project_items:
            try:
                await _require_annotation_project_write(db, user, workspace_id, annotation)
                writable_project_items[project_item_id] = True
            except (
                PermissionDenied,
                ResourceUnavailable,
                WorkspaceLifecycleError,
                WorkspaceMembershipRequired,
            ):
                writable_project_items[project_item_id] = False
        if writable_project_items[project_item_id]:
            editable.add(reply.id)
    return editable


async def _visible_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    *,
    deleted: bool,
) -> PdfAnnotation:
    await require_readable_item(db, user, workspace_id, item_id)
    record = await db.scalar(
        select(PdfAnnotation).where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.workspace_id == workspace_id,
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
    if (
        record is None
        or revision is None
        or (record.deleted_at is not None) != deleted
        or record.hidden_at is not None
        or record.archived_at is not None
    ):
        raise ResourceUnavailable("Annotation not found")
    if record.scope is AnnotationScope.private:
        if record.author_id != user.id:
            raise ResourceUnavailable("Annotation not found")
        return record
    project_item = await db.scalar(
        select(ProjectItem).where(
            ProjectItem.id == record.project_item_id,
            ProjectItem.workspace_id == workspace_id,
            ProjectItem.item_id == item_id,
        )
    )
    if project_item is None:
        raise ResourceUnavailable("Annotation not found")
    await require_project_context(
        db,
        user,
        workspace_id,
        project_item.project_id,
        Capability.workspace_read,
    )
    return record


async def require_visible_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
) -> PdfAnnotation:
    return await _visible_annotation(db, user, workspace_id, item_id, annotation_id, deleted=False)


async def require_editable_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
) -> PdfAnnotation:
    record = await require_visible_annotation(db, user, workspace_id, item_id, annotation_id)
    await _require_annotation_write(db, user, workspace_id, record)
    return record


async def require_restorable_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
) -> PdfAnnotation:
    record = await _visible_annotation(db, user, workspace_id, item_id, annotation_id, deleted=True)
    await _require_annotation_write(db, user, workspace_id, record)
    return record


async def require_visible_annotation_for_reply_mutation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
) -> tuple[User, PdfAnnotation]:
    record = await require_visible_annotation(db, user, workspace_id, item_id, annotation_id)
    if record.locked_at is not None:
        raise PermissionDenied("Annotation is locked")
    if record.scope is AnnotationScope.private:
        await require_workspace_capability(
            db, user, workspace_id, Capability.annotations_private_write
        )
    else:
        await _require_annotation_project_write(db, user, workspace_id, record)
    return user, record
