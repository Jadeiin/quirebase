from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, or_, select

from quirebase.audit import record_event
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.core.storage import get_object_store
from quirebase.documents.revisions import delete_unreferenced_objects
from quirebase.models import Attachment, FileRevision, Item, User
from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def list_global_items(
    db: AsyncSession,
    admin: User,
    search: str = "",
    owner_id: str | None = None,
    has_pdf: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Item], int]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    query = select(Item)
    count_query = select(func.count(Item.id))
    filters = []
    if search.strip():
        search_value = search.strip()
        term = f"%{search_value}%"
        matching_ids = await search_index(db).matching_item_ids(db, search_value)
        filters.append(
            or_(
                Item.id.in_(matching_ids),
                Item.title.ilike(term),
                Item.authors.ilike(term),
                Item.doi.ilike(term),
                Item.id == search_value,
            )
        )
    if owner_id:
        filters.append(Item.created_by == owner_id)
    if has_pdf is True:
        filters.append(Item.id.in_(select(FileRevision.item_id)))
    elif has_pdf is False:
        filters.append(Item.id.not_in(select(FileRevision.item_id)))
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)

    total = await db.scalar(count_query) or 0
    offset = max(0, (page - 1) * page_size)
    items = list(
        (
            await db.scalars(query.order_by(Item.created_at.desc()).offset(offset).limit(page_size))
        ).all()
    )
    return items, total


async def get_storage_metrics(db: AsyncSession, admin: User) -> dict[str, Any]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    store = get_object_store()

    total_items = await db.scalar(select(func.count(Item.id))) or 0
    revisions = list((await db.scalars(select(FileRevision))).all())
    attachments = list((await db.scalars(select(Attachment))).all())

    revisions_bytes = 0
    missing_revisions = 0
    for revision in revisions:
        if await store.exists(revision.object_key):
            revisions_bytes += (await store.head(revision.object_key)).size
        else:
            missing_revisions += 1
    attachments_bytes = 0
    missing_attachments = 0
    for attachment in attachments:
        if await store.exists(attachment.object_key):
            attachments_bytes += (await store.head(attachment.object_key)).size
        else:
            missing_attachments += 1
    thumbnail_keys = tuple(
        revision.thumbnail_object_key for revision in revisions if revision.thumbnail_object_key
    )
    thumbnails = [await store.head(key) for key in thumbnail_keys if await store.exists(key)]
    thumbnails_count = len(thumbnails)
    thumbnails_bytes = sum(item.size for item in thumbnails)

    total_disk_bytes = revisions_bytes + attachments_bytes + thumbnails_bytes

    return {
        "items_count": total_items,
        "revisions_count": len(revisions),
        "attachments_count": len(attachments),
        "thumbnails_count": thumbnails_count,
        "revisions_bytes": revisions_bytes,
        "attachments_bytes": attachments_bytes,
        "thumbnails_bytes": thumbnails_bytes,
        "total_disk_bytes": total_disk_bytes,
        "missing_files_count": missing_revisions + missing_attachments,
    }


async def _delete_item(
    db: AsyncSession, actor: User, item_id: str, *, require_admin: bool = False
) -> None:
    if require_admin and actor.role != "administrator":
        raise ResourceUnavailable("administrator required")
    item = await db.get(Item, item_id)
    if item is None:
        raise ResourceNotFound("item not found")
    if not require_admin and item.created_by != actor.id and actor.role != "administrator":
        raise ResourceUnavailable("item owner required")

    title = item.title
    # Collect keys to clean up from storage
    cleanup_keys = list(
        (
            await db.scalars(select(FileRevision.object_key).where(FileRevision.item_id == item.id))
        ).all()
    )
    cleanup_keys.extend(
        (await db.scalars(select(Attachment.object_key).where(Attachment.item_id == item.id))).all()
    )

    thumbnail_keys = tuple(
        key
        for key in (
            await db.scalars(
                select(FileRevision.thumbnail_object_key).where(FileRevision.item_id == item.id)
            )
        ).all()
        if key
    )

    # Remove from search index
    await search_index(db).remove_item(db, item.id)

    # Explicitly delete child relations for cross-dialect foreign key safety
    await db.execute(delete(FileRevision).where(FileRevision.item_id == item.id))
    await db.execute(delete(Attachment).where(Attachment.item_id == item.id))

    # Delete entity from database
    await db.delete(item)

    # Record audit event before commit
    record_event(
        db,
        actor.id,
        "admin.item.delete" if require_admin else "item.delete",
        "item",
        item.id,
        detail={"title": title},
    )
    await db.commit()
    store = get_object_store()
    for key in thumbnail_keys:
        await store.delete(key)

    # Clean object store files after a successful commit and a centralized reference check.
    if cleanup_keys:
        await delete_unreferenced_objects(db, cleanup_keys)


async def delete_item(db: AsyncSession, actor: User, item_id: str) -> None:
    """Permanently delete one Item owned by the actor or an administrator."""
    await _delete_item(db, actor, item_id)


async def admin_delete_item(db: AsyncSession, admin: User, item_id: str) -> None:
    await _delete_item(db, admin, item_id, require_admin=True)
