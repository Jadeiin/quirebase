from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, or_, select

from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.core.storage import LocalObjectStore
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
    store = LocalObjectStore()
    settings = get_settings()

    total_items = await db.scalar(select(func.count(Item.id))) or 0
    revisions = list((await db.scalars(select(FileRevision))).all())
    attachments = list((await db.scalars(select(Attachment))).all())

    (
        revisions_bytes,
        missing_revisions,
        attachments_bytes,
        missing_attachments,
        thumbnails_count,
        thumbnails_bytes,
    ) = await asyncio.to_thread(
        _storage_metrics,
        store,
        settings.object_dir / "thumbnails",
        revisions,
        attachments,
    )

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


def _storage_metrics(
    store: LocalObjectStore,
    thumbnails_dir,
    revisions: list[FileRevision],
    attachments: list[Attachment],
) -> tuple[int, int, int, int, int, int]:
    revisions_bytes = 0
    missing_revisions = 0
    for revision in revisions:
        path = store.path(revision.object_key)
        if path.is_file():
            revisions_bytes += path.stat().st_size
        else:
            missing_revisions += 1

    attachments_bytes = 0
    missing_attachments = 0
    for attachment in attachments:
        path = store.path(attachment.object_key)
        if path.is_file():
            attachments_bytes += path.stat().st_size
        else:
            missing_attachments += 1

    thumbnails_count = 0
    thumbnails_bytes = 0
    if thumbnails_dir.exists():
        for thumbnail in thumbnails_dir.glob("*.png"):
            if thumbnail.is_file():
                thumbnails_count += 1
                thumbnails_bytes += thumbnail.stat().st_size
    return (
        revisions_bytes,
        missing_revisions,
        attachments_bytes,
        missing_attachments,
        thumbnails_count,
        thumbnails_bytes,
    )


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

    # Clean thumbnail if present
    settings = get_settings()
    for rev_id in (
        await db.scalars(select(FileRevision.id).where(FileRevision.item_id == item.id))
    ).all():
        thumb_path = settings.object_dir / "thumbnails" / f"{rev_id}.png"
        if await asyncio.to_thread(thumb_path.exists):
            with contextlib.suppress(OSError):
                await asyncio.to_thread(thumb_path.unlink)

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

    # Clean object store files after a successful commit and a centralized reference check.
    if cleanup_keys:
        await delete_unreferenced_objects(db, cleanup_keys)


async def delete_item(db: AsyncSession, actor: User, item_id: str) -> None:
    """Permanently delete one Item owned by the actor or an administrator."""
    await _delete_item(db, actor, item_id)


async def admin_delete_item(db: AsyncSession, admin: User, item_id: str) -> None:
    await _delete_item(db, admin, item_id, require_admin=True)
