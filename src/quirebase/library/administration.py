from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select

from quirebase.access.items import require_editable_item
from quirebase.access.workspaces import Capability, require_workspace_capability
from quirebase.audit import record_event
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.documents import enqueue_object_cleanup
from quirebase.models import Attachment, FileRevision, Item, ObjectIntegrityScan, User
from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_storage_metrics(db: AsyncSession, admin: User) -> dict[str, Any]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    total_items = await db.scalar(select(func.count(Item.id))) or 0
    revisions_count, revisions_bytes = (
        await db.execute(
            select(func.count(FileRevision.id), func.coalesce(func.sum(FileRevision.size), 0))
        )
    ).one()
    attachments_count, attachments_bytes = (
        await db.execute(
            select(func.count(Attachment.id), func.coalesce(func.sum(Attachment.size), 0))
        )
    ).one()
    thumbnails_count, thumbnails_bytes = (
        await db.execute(
            select(
                func.count(FileRevision.thumbnail_object_key),
                func.coalesce(func.sum(FileRevision.thumbnail_size), 0),
            )
        )
    ).one()
    latest_scan = await db.scalar(
        select(ObjectIntegrityScan).order_by(ObjectIntegrityScan.checked_at.desc()).limit(1)
    )

    total_disk_bytes = revisions_bytes + attachments_bytes + thumbnails_bytes

    return {
        "items_count": total_items,
        "revisions_count": revisions_count,
        "attachments_count": attachments_count,
        "thumbnails_count": thumbnails_count,
        "revisions_bytes": revisions_bytes,
        "attachments_bytes": attachments_bytes,
        "thumbnails_bytes": thumbnails_bytes,
        "total_disk_bytes": total_disk_bytes,
        "missing_files_count": latest_scan.missing_count if latest_scan else 0,
        "integrity_status": latest_scan.status if latest_scan else "not_checked",
        "integrity_checked_at": latest_scan.checked_at if latest_scan else None,
    }


async def _delete_item(db: AsyncSession, actor: User, workspace_id: str, item_id: str) -> None:
    await require_workspace_capability(db, actor, workspace_id, Capability.items_delete)
    await require_editable_item(db, actor, workspace_id, item_id)
    item = await db.scalar(
        select(Item).where(Item.id == item_id, Item.workspace_id == workspace_id).with_for_update()
    )
    if item is None:
        raise ResourceNotFound("item not found")

    title = item.title
    # Collect keys to clean up from storage
    cleanup_keys = list(
        (
            await db.scalars(
                select(FileRevision.object_key).where(
                    FileRevision.workspace_id == workspace_id,
                    FileRevision.item_id == item.id,
                )
            )
        ).all()
    )
    cleanup_keys.extend(
        (
            await db.scalars(
                select(Attachment.object_key).where(
                    Attachment.workspace_id == workspace_id,
                    Attachment.item_id == item.id,
                )
            )
        ).all()
    )

    thumbnail_keys = tuple(
        key
        for key in (
            await db.scalars(
                select(FileRevision.thumbnail_object_key).where(
                    FileRevision.workspace_id == workspace_id,
                    FileRevision.item_id == item.id,
                )
            )
        ).all()
        if key
    )

    # Explicitly delete child relations for cross-dialect foreign key safety
    await db.execute(
        delete(FileRevision).where(
            FileRevision.workspace_id == workspace_id,
            FileRevision.item_id == item.id,
        )
    )
    await db.execute(
        delete(Attachment).where(
            Attachment.workspace_id == workspace_id,
            Attachment.item_id == item.id,
        )
    )

    # Revision projections are owned by FileRevision and cascade on PostgreSQL;
    # the SQLite adapter clears them explicitly.
    await search_index(db).remove_item(db, item.id)

    # Delete entity from database
    await db.delete(item)

    # Record audit event before commit
    record_event(
        db,
        actor.id,
        "item.delete",
        "item",
        item.id,
        detail={"title": title},
        workspace_id=workspace_id,
        authorization_capability=Capability.items_delete.value,
    )
    await enqueue_object_cleanup(
        db,
        [*cleanup_keys, *thumbnail_keys],
        actor_id=actor.id,
        workspace_id=workspace_id,
        operation="item_delete",
        target_id=item.id,
    )
    await db.commit()


async def delete_item(db: AsyncSession, actor: User, workspace_id: str, item_id: str) -> None:
    """Permanently delete one Workspace Item with the destructive capability."""
    await _delete_item(db, actor, workspace_id, item_id)
