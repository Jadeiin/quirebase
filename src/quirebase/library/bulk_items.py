"""Apply one operation to a user-selected set of Items."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.access.items import (
    can_edit_item,
    require_accessible_items,
)
from quirebase.access.projects import project_member
from quirebase.audit import record_event
from quirebase.core.errors import (
    PermissionDenied,
    ValidationFailure,
)
from quirebase.documents import enqueue_object_cleanup
from quirebase.documents.bundles import (
    ItemDownloadBundle,
    assemble_document_bundle,
)
from quirebase.library.tags import get_or_create_tag
from quirebase.models import (
    Attachment,
    FileRevision,
    ItemTag,
    ProjectItem,
    User,
)
from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def apply_bulk_item_action(
    db: AsyncSession,
    user: User,
    item_ids: list[str],
    action: str,
    project_id: str = "",
    tag_name: str = "",
    confirm_delete: str = "",
) -> list[str]:
    items = await require_accessible_items(db, user, item_ids)

    # Fail-closed: All selected items must be editable for mutating bulk actions
    for item in items:
        if not await can_edit_item(db, user, item.id):
            raise PermissionDenied("all selected items must be editable")

    cleanup_keys: list[str] = []
    if action in ("add_project", "project_add"):
        membership = await project_member(db, user, project_id)
        if membership is None or membership.role not in ("owner", "editor"):
            raise ValidationFailure("choose an editable project")
        for item in items:
            if await db.get(ProjectItem, (project_id, item.id)) is None:
                db.add(ProjectItem(project_id=project_id, item_id=item.id))
                await search_index(db).index_item(db, item.id)
        audit_action = "library.bulk.add_project"
    elif action in ("add_tag", "tag"):
        tag_record = await get_or_create_tag(db, user, tag_name)
        for item in items:
            if await db.get(ItemTag, (item.id, tag_record.id)) is None:
                db.add(ItemTag(item_id=item.id, tag_id=tag_record.id))
                await search_index(db).index_item(db, item.id)
        audit_action = "library.bulk.add_tag"
    elif action in ("delete_items", "delete"):
        if confirm_delete != "delete":
            raise ValidationFailure("confirm deletion of the selected items")
        if user.role != "administrator" and any(item.created_by != user.id for item in items):
            raise PermissionDenied("only item owners can permanently delete items")
        cleanup_keys = list(
            (
                await db.scalars(
                    select(FileRevision.object_key).where(
                        FileRevision.item_id.in_([item.id for item in items])
                    )
                )
            ).all()
        )
        cleanup_keys.extend(
            (
                await db.scalars(
                    select(Attachment.object_key).where(
                        Attachment.item_id.in_([item.id for item in items])
                    )
                )
            ).all()
        )
        cleanup_keys.extend(
            key
            for key in (
                await db.scalars(
                    select(FileRevision.thumbnail_object_key).where(
                        FileRevision.item_id.in_([item.id for item in items])
                    )
                )
            ).all()
            if key
        )
        for item in items:
            await search_index(db).remove_item(db, item.id)
            await db.delete(item)
        audit_action = "library.bulk.delete_items"
    else:
        raise ValidationFailure("unknown bulk action")

    record_event(
        db,
        user.id,
        audit_action,
        "item",
        None,
        detail={"item_ids": [item.id for item in items]},
    )
    if cleanup_keys:
        await enqueue_object_cleanup(
            db,
            cleanup_keys,
            owner_id=user.id,
            operation="bulk_item_delete",
        )
    await db.commit()

    return cleanup_keys


async def download_selected_item_documents(
    db: AsyncSession,
    user: User,
    item_ids: list[str],
    *,
    include_annotations: bool = False,
    include_supplements: bool = False,
    timezone: str | None = None,
) -> ItemDownloadBundle:
    items = await require_accessible_items(db, user, item_ids)
    bundle = await assemble_document_bundle(
        db,
        user,
        items,
        include_annotations=include_annotations,
        include_supplements=include_supplements,
        timezone=timezone,
    )
    record_event(
        db,
        user.id,
        "library.bulk.download_pdfs",
        "item",
        None,
        detail={
            "item_ids": [item.id for item in items],
            "include_annotations": include_annotations,
            "include_supplements": include_supplements,
        },
    )
    await db.commit()
    return bundle
