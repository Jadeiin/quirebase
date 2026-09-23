from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.access.items import can_read_item
from quirebase.core.errors import ResourceUnavailable
from quirebase.models import (
    AnnotationScope,
    FileRevision,
    Item,
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


def can_edit_annotation(user: User, annotation: PdfAnnotation) -> bool:
    return annotation.author_id == user.id


def editable_annotation_ids(user: User, annotations: list[PdfAnnotation]) -> set[str]:
    """Only the author may rewrite authored Annotation state."""
    return {annotation.id for annotation in annotations if annotation.author_id == user.id}


def editable_annotation_reply_ids(user: User, replies: list[PdfAnnotationReply]) -> set[str]:
    """Only the author may rewrite authored Reply state."""
    return {reply.id for reply in replies if reply.author_id == user.id}


async def can_delete_annotation(db: AsyncSession, user: User, annotation: PdfAnnotation) -> bool:
    if user.role == SystemRole.administrator.value or annotation.author_id == user.id:
        return True
    if annotation.scope is not AnnotationScope.project or annotation.project_item_id is None:
        return False
    return (
        await db.scalar(
            select(ProjectMember.project_id)
            .join(ProjectItem, ProjectItem.project_id == ProjectMember.project_id)
            .where(
                ProjectItem.id == annotation.project_item_id,
                ProjectMember.user_id == user.id,
                ProjectMember.role == ProjectRole.admin,
            )
            .limit(1)
        )
        is not None
    )


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
        .with_for_update(read=True)
    )
    item = await db.scalar(select(Item).where(Item.id == item_id).with_for_update(read=True))
    if locked_user is None or not locked_user.active or item is None:
        raise ResourceUnavailable("annotation not found or cannot be viewed")
    record = await db.scalar(
        select(PdfAnnotation).where(PdfAnnotation.id == annotation_id).with_for_update(read=True)
    )
    revision = (
        await db.scalar(
            select(FileRevision)
            .join(ItemFileRevision, ItemFileRevision.file_revision_id == FileRevision.id)
            .where(ItemFileRevision.id == record.item_file_revision_id)
        )
        if record
        else None
    )
    if (
        record is None
        or revision is None
        or await db.scalar(
            select(ItemFileRevision.id).where(
                ItemFileRevision.id == record.item_file_revision_id,
                ItemFileRevision.item_id == item_id,
            )
        )
        is None
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
        if visible_scope and not administrator and item.owner_id != locked_user.id:
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
                .with_for_update(read=True)
            )
            visible_scope = access_grant is not None
    elif record.project_item_id:
        project_item = await db.scalar(
            select(ProjectItem)
            .where(ProjectItem.id == record.project_item_id, ProjectItem.item_id == item_id)
            .with_for_update(read=True)
        )
        if administrator:
            visible_scope = project_item is not None
        else:
            membership = await db.scalar(
                select(ProjectMember)
                .join(ProjectItem, ProjectItem.project_id == ProjectMember.project_id)
                .where(
                    ProjectItem.id == record.project_item_id,
                    ProjectMember.user_id == locked_user.id,
                )
                .with_for_update(read=True)
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
    revision = (
        await db.scalar(
            select(FileRevision)
            .join(ItemFileRevision, ItemFileRevision.file_revision_id == FileRevision.id)
            .where(ItemFileRevision.id == record.item_file_revision_id)
        )
        if record
        else None
    )
    administrator = user.role == SystemRole.administrator.value
    visible_scope = False
    if record is not None:
        if record.scope is AnnotationScope.private:
            visible_scope = administrator or record.author_id == user.id
        elif record.project_item_id:
            visible_scope = await db.get(ProjectItem, record.project_item_id) is not None and (
                administrator
                or await db.scalar(
                    select(ProjectMember.project_id)
                    .join(ProjectItem, ProjectItem.project_id == ProjectMember.project_id)
                    .where(
                        ProjectItem.id == record.project_item_id, ProjectMember.user_id == user.id
                    )
                )
                is not None
            )
    if (
        record is None
        or revision is None
        or await db.scalar(
            select(ItemFileRevision.id).where(
                ItemFileRevision.id == record.item_file_revision_id,
                ItemFileRevision.item_id == item_id,
            )
        )
        is None
        or not visible_scope
        or not await can_read_item(db, user, item_id)
    ):
        raise ResourceUnavailable("annotation not found or cannot be viewed")
    return record


async def require_editable_annotation(
    db: AsyncSession, user: User, item_id: str, annotation_id: str
) -> PdfAnnotation:
    record = await require_visible_annotation(db, user, item_id, annotation_id)
    if not can_edit_annotation(user, record):
        raise ResourceUnavailable("annotation not found or cannot be edited")
    return record


async def require_deletable_annotation(
    db: AsyncSession, user: User, item_id: str, annotation_id: str
) -> PdfAnnotation:
    record = await require_visible_annotation(db, user, item_id, annotation_id)
    if not await can_delete_annotation(db, user, record):
        raise ResourceUnavailable("annotation not found or cannot be deleted")
    return record
