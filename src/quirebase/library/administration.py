from __future__ import annotations

import contextlib
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.core.storage import LocalObjectStore
from quirebase.models import Attachment, FileRevision, Item, User
from quirebase.search import search_index


def list_global_items(
    db: Session,
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
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                Item.title.ilike(term),
                Item.authors.ilike(term),
                Item.doi.ilike(term),
                Item.id == search.strip(),
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

    total = db.scalar(count_query) or 0
    offset = max(0, (page - 1) * page_size)
    items = list(
        db.scalars(query.order_by(Item.created_at.desc()).offset(offset).limit(page_size)).all()
    )
    return items, total


def get_storage_metrics(db: Session, admin: User) -> dict[str, Any]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    store = LocalObjectStore()
    settings = get_settings()

    total_items = db.scalar(select(func.count(Item.id))) or 0
    revisions = list(db.scalars(select(FileRevision)).all())
    attachments = list(db.scalars(select(Attachment)).all())

    revisions_bytes = 0
    missing_revisions = 0
    for rev in revisions:
        path = store.path(rev.object_key)
        if path.is_file():
            revisions_bytes += path.stat().st_size
        else:
            missing_revisions += 1

    attachments_bytes = 0
    missing_attachments = 0
    for att in attachments:
        path = store.path(att.object_key)
        if path.is_file():
            attachments_bytes += path.stat().st_size
        else:
            missing_attachments += 1

    thumbnails_dir = settings.object_dir / "thumbnails"
    thumbnails_count = 0
    thumbnails_bytes = 0
    if thumbnails_dir.exists():
        for thumb in thumbnails_dir.glob("*.png"):
            if thumb.is_file():
                thumbnails_count += 1
                thumbnails_bytes += thumb.stat().st_size

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


def admin_delete_item(db: Session, admin: User, item_id: str) -> None:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    item = db.get(Item, item_id)
    if item is None:
        raise ResourceNotFound("item not found")

    title = item.title
    # Collect keys to clean up from storage
    cleanup_keys = list(
        db.scalars(select(FileRevision.object_key).where(FileRevision.item_id == item.id)).all()
    )
    cleanup_keys.extend(
        db.scalars(select(Attachment.object_key).where(Attachment.item_id == item.id)).all()
    )

    # Clean thumbnail if present
    settings = get_settings()
    for rev_id in db.scalars(select(FileRevision.id).where(FileRevision.item_id == item.id)).all():
        thumb_path = settings.object_dir / "thumbnails" / f"{rev_id}.png"
        if thumb_path.exists():
            with contextlib.suppress(OSError):
                thumb_path.unlink()

    # Remove from search index
    search_index(db).remove_item(db, item.id)

    # Explicitly delete child relations for cross-dialect foreign key safety
    db.execute(delete(FileRevision).where(FileRevision.item_id == item.id))
    db.execute(delete(Attachment).where(Attachment.item_id == item.id))

    # Delete entity from database
    db.delete(item)

    # Record audit event before commit
    record_event(
        db,
        admin.id,
        "admin.item.delete",
        "item",
        item.id,
        detail={"title": title},
    )
    db.commit()

    # Clean object store files after successful commit only if not referenced by other items
    store = LocalObjectStore()
    if cleanup_keys:
        with Session(db.bind) as cleanup_db:
            for object_key in cleanup_keys:
                still_used = cleanup_db.scalar(
                    select(FileRevision.id).where(FileRevision.object_key == object_key).limit(1)
                ) or cleanup_db.scalar(
                    select(Attachment.id).where(Attachment.object_key == object_key).limit(1)
                )
                if not still_used:
                    store.delete(object_key)
