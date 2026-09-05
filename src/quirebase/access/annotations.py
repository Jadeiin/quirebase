from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.access.items import can_read_item
from quirebase.access.projects import project_member
from quirebase.core.errors import ResourceUnavailable
from quirebase.models import (
    AnnotationScope,
    FileRevision,
    Item,
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


async def can_edit_annotation(db: AsyncSession, user: User, annotation: PdfAnnotation) -> bool:
    return annotation.id in await editable_annotation_ids(db, user, [annotation])


async def editable_annotation_ids(
    db: AsyncSession, user: User, annotations: list[PdfAnnotation]
) -> set[str]:
    """Resolve editable Annotations with at most one Project membership query."""
    if user.role == SystemRole.administrator.value:
        return {annotation.id for annotation in annotations}

    editable = {annotation.id for annotation in annotations if annotation.author_id == user.id}
    project_ids = {
        annotation.project_id
        for annotation in annotations
        if annotation.id not in editable
        and annotation.scope is AnnotationScope.project
        and annotation.project_id
    }
    if not project_ids:
        return editable
    owned_project_ids = set(
        (
            await db.scalars(
                select(ProjectMember.project_id).where(
                    ProjectMember.user_id == user.id,
                    ProjectMember.role == ProjectRole.owner,
                    ProjectMember.project_id.in_(project_ids),
                )
            )
        ).all()
    )
    editable.update(
        annotation.id
        for annotation in annotations
        if annotation.scope is AnnotationScope.project
        and annotation.project_id in owned_project_ids
    )
    return editable


async def editable_annotation_reply_ids(
    db: AsyncSession,
    user: User,
    replies: list[PdfAnnotationReply],
    annotations: dict[str, PdfAnnotation],
) -> set[str]:
    """Resolve editable Annotation Replies with at most one Project membership query."""
    if user.role == SystemRole.administrator.value:
        return {reply.id for reply in replies}
    editable = {reply.id for reply in replies if reply.author_id == user.id}
    project_ids = {
        annotation.project_id
        for reply in replies
        if reply.id not in editable
        and (annotation := annotations.get(reply.annotation_id)) is not None
        and annotation.scope is AnnotationScope.project
        and annotation.project_id
    }
    if not project_ids:
        return editable
    owned_project_ids = set(
        (
            await db.scalars(
                select(ProjectMember.project_id).where(
                    ProjectMember.user_id == user.id,
                    ProjectMember.role == ProjectRole.owner,
                    ProjectMember.project_id.in_(project_ids),
                )
            )
        ).all()
    )
    editable.update(
        reply.id
        for reply in replies
        if (annotation := annotations.get(reply.annotation_id)) is not None
        and annotation.project_id in owned_project_ids
    )
    return editable


async def require_visible_annotation(
    db: AsyncSession, user: User, item_id: str, annotation_id: str
) -> PdfAnnotation:
    return await _require_visible_annotation(db, user, item_id, annotation_id, deleted=False)


async def _lock_reply_mutation_context(
    db: AsyncSession, user: User, item_id: str, annotation_id: str
) -> tuple[User, Item, PdfAnnotation]:
    locked_user = await db.scalar(
        select(User)
        .where(User.id == user.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    item = await db.scalar(select(Item).where(Item.id == item_id).with_for_update())
    if locked_user is None or not locked_user.active or item is None:
        raise ResourceUnavailable("annotation not found or cannot be viewed")
    record = await db.scalar(
        select(PdfAnnotation).where(PdfAnnotation.id == annotation_id).with_for_update()
    )
    revision = await db.get(FileRevision, record.file_revision_id) if record else None
    if (
        record is None
        or record.deleted_at is not None
        or revision is None
        or revision.item_id != item_id
    ):
        raise ResourceUnavailable("annotation not found or cannot be viewed")
    return locked_user, item, record


async def require_visible_annotation_for_reply_mutation(
    db: AsyncSession,
    user: User,
    item_id: str,
    annotation_id: str,
) -> tuple[User, PdfAnnotation]:
    """Authorize a reply write while locking every row that can revoke access."""
    locked_user, item, record = await _lock_reply_mutation_context(db, user, item_id, annotation_id)
    visible_scope = False
    administrator = locked_user.role == SystemRole.administrator.value
    if record.scope is AnnotationScope.private:
        visible_scope = administrator or record.author_id == locked_user.id
        if visible_scope and not administrator and item.created_by != locked_user.id:
            access_grant = await db.scalar(
                select(ProjectMember)
                .join(
                    ProjectItem,
                    ProjectItem.project_id == ProjectMember.project_id,
                )
                .where(
                    ProjectMember.user_id == locked_user.id,
                    ProjectItem.item_id == item_id,
                )
                .order_by(ProjectMember.project_id)
                .limit(1)
                .with_for_update()
            )
            visible_scope = access_grant is not None
    elif record.project_id:
        project_item = await db.scalar(
            select(ProjectItem)
            .where(
                ProjectItem.project_id == record.project_id,
                ProjectItem.item_id == item_id,
            )
            .with_for_update()
        )
        if administrator:
            visible_scope = project_item is not None
        else:
            membership = await db.scalar(
                select(ProjectMember)
                .where(
                    ProjectMember.project_id == record.project_id,
                    ProjectMember.user_id == locked_user.id,
                )
                .with_for_update()
            )
            visible_scope = project_item is not None and membership is not None
    if not visible_scope:
        raise ResourceUnavailable("annotation not found or cannot be viewed")
    return locked_user, record


async def _require_visible_annotation(
    db: AsyncSession,
    user: User,
    item_id: str,
    annotation_id: str,
    *,
    deleted: bool,
) -> PdfAnnotation:
    record = await db.scalar(select(PdfAnnotation).where(PdfAnnotation.id == annotation_id))
    revision = await db.get(FileRevision, record.file_revision_id) if record else None
    administrator = user.role == SystemRole.administrator.value
    visible_scope = False
    if record is not None:
        if record.scope is AnnotationScope.private:
            visible_scope = administrator or record.author_id == user.id
        elif record.project_id:
            visible_scope = await db.get(
                ProjectItem, (record.project_id, item_id)
            ) is not None and (
                administrator or await project_member(db, user, record.project_id) is not None
            )
    if (
        record is None
        or (record.deleted_at is not None) != deleted
        or revision is None
        or revision.item_id != item_id
        or not visible_scope
        or not await can_read_item(db, user, item_id)
    ):
        raise ResourceUnavailable("annotation not found or cannot be viewed")
    return record


async def require_editable_annotation(
    db: AsyncSession, user: User, item_id: str, annotation_id: str
) -> PdfAnnotation:
    record = await require_visible_annotation(db, user, item_id, annotation_id)
    if not await can_edit_annotation(db, user, record):
        raise ResourceUnavailable("annotation not found or cannot be edited")
    return record


async def require_restorable_annotation(
    db: AsyncSession, user: User, item_id: str, annotation_id: str
) -> PdfAnnotation:
    record = await _require_visible_annotation(db, user, item_id, annotation_id, deleted=True)
    if not await can_edit_annotation(db, user, record):
        raise ResourceUnavailable("annotation not found or cannot be restored")
    return record
