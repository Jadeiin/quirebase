"""Apply one operation to a user-selected set of Items."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from quirebase.access.items import (
    can_edit_item,
    require_accessible_items,
    require_editable_item_for_mutation,
)
from quirebase.audit import record_event
from quirebase.core.errors import (
    PermissionDenied,
    ResourceUnavailable,
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
    Item,
    ItemTag,
    User,
)
from quirebase.projects import add_items_to_project
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
        try:
            await add_items_to_project(db, user, project_id, [item.id for item in items])
        except ResourceUnavailable as error:
            raise ValidationFailure("choose an editable project") from error
        audit_action = "library.bulk.add_project"
    elif action in ("add_tag", "tag"):
        # Hold each active Project grant while adding associations so an
        # archive cannot race the authorization check.  Stable Item ordering
        # keeps concurrent bulk requests from acquiring grant locks differently.
        for item in sorted(items, key=lambda candidate: candidate.id):
            await require_editable_item_for_mutation(db, user, item.id)
        tag_record = await get_or_create_tag(db, user, tag_name)
        dialect = db.get_bind().dialect.name
        insert = pg_insert(ItemTag) if dialect == "postgresql" else sqlite_insert(ItemTag)
        await db.execute(
            insert.values([
                {"item_id": item.id, "tag_id": tag_record.id} for item in items
            ]).on_conflict_do_nothing(index_elements=["item_id", "tag_id"])
        )
        audit_action = "library.bulk.add_tag"
    elif action in ("delete_items", "delete"):
        if confirm_delete != "delete":
            raise ValidationFailure("confirm deletion of the selected items")
        # Lock every Item root in stable order before collecting child object keys.  Upload and
        # import finalizers use the same parent lock, so no new child can commit after this
        # snapshot and escape the cleanup intent.
        requested_ids = tuple(sorted({item.id for item in items}))
        locked_items = list(
            (
                await db.scalars(
                    select(Item)
                    .where(Item.id.in_(requested_ids))
                    .order_by(Item.id)
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
            ).all()
        )
        if len(locked_items) != len(requested_ids):
            raise ResourceUnavailable("one or more selected items no longer exist")
        items = locked_items
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
