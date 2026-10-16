"""Apply one operation to a user-selected set of Items."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from quirebase.access import ResourceAction, require_workspace_action
from quirebase.access.items import (
    require_accessible_items,
    require_item_action,
)
from quirebase.audit import record_event
from quirebase.core.errors import (
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.documents import delete_item_documents, enqueue_object_cleanup
from quirebase.documents.bundles import (
    ItemDownloadBundle,
    assemble_document_bundle,
)
from quirebase.library.tags import TagConflict, _assign_item_tags, get_or_create_tag
from quirebase.models import (
    Item,
    User,
)
from quirebase.projects import add_items_to_project
from quirebase.search import search_index

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


async def apply_bulk_item_action(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_ids: list[UUID],
    action: str,
    project_id: UUID | None = None,
    tag_name: str = "",
    confirm_delete: str = "",
) -> None:
    items = await require_accessible_items(db, user, workspace_id, item_ids)

    cleanup_keys: tuple[str, ...] = ()
    if action in ("add_project", "project_add"):
        if project_id is None:
            raise ValidationFailure("Project is required")
        try:
            await add_items_to_project(
                db, user, workspace_id, project_id, [item.id for item in items]
            )
        except ResourceUnavailable as error:
            raise ValidationFailure("choose an editable project") from error
        audit_action = "library.bulk.add_project"
    elif action in ("add_tag", "tag"):
        # Revalidate each Item's Tag-use authority and existence before adding
        # associations. Stable Item ordering keeps these checks deterministic.
        for item in sorted(items, key=lambda candidate: candidate.id):
            await require_item_action(db, user, workspace_id, item.id, ResourceAction.tag_use)
        tag_record = await get_or_create_tag(db, user, workspace_id, tag_name)
        try:
            await _assign_item_tags(db, workspace_id, [item.id for item in items], tag_record.id)
        except IntegrityError as error:
            # A root may disappear before insertion. The association savepoint
            # rolls back every new link and leaves the caller transaction usable.
            raise TagConflict(
                "tag associations changed concurrently; retry the bulk action"
            ) from error
        audit_action = "library.bulk.add_tag"
    elif action in ("delete_items", "delete"):
        await require_workspace_action(db, user, workspace_id, ResourceAction.item_delete)
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
                    .where(Item.workspace_id == workspace_id, Item.id.in_(requested_ids))
                    .order_by(Item.id)
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
            ).all()
        )
        if len(locked_items) != len(requested_ids):
            raise ResourceUnavailable("one or more selected items no longer exist")
        items = locked_items
        cleanup_keys = await delete_item_documents(db, workspace_id, requested_ids)
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
        workspace_id=workspace_id,
        authorization_resource_action=(
            ResourceAction.project_item_manage.value
            if action in ("add_project", "project_add")
            else ResourceAction.tag_use.value
            if action in ("add_tag", "tag")
            else ResourceAction.item_delete.value
        ),
    )
    if cleanup_keys:
        await enqueue_object_cleanup(
            db,
            cleanup_keys,
            actor_id=user.id,
            workspace_id=workspace_id,
            operation="bulk_item_delete",
        )
    await db.commit()


async def download_selected_item_documents(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_ids: list[UUID],
    *,
    include_annotations: bool = False,
    include_supplements: bool = False,
    timezone: str | None = None,
) -> ItemDownloadBundle:
    items = await require_accessible_items(db, user, workspace_id, item_ids)
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
        workspace_id=workspace_id,
    )
    await db.commit()
    return bundle
