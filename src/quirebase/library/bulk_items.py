"""Apply one operation to a user-selected set of Items."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, assert_never

from sqlalchemy import delete, select
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
    ItemTag,
    Tag,
    User,
)
from quirebase.projects import add_items_to_project, remove_items_from_project
from quirebase.search import search_index

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class BulkItemAction(StrEnum):
    add_project = "add_project"
    remove_project = "remove_project"
    add_tag = "add_tag"
    remove_tag = "remove_tag"
    delete_items = "delete_items"

    @property
    def audit_action(self) -> str:
        return f"library.bulk.{self.value}"

    @property
    def resource_action(self) -> ResourceAction:
        match self:
            case BulkItemAction.add_project | BulkItemAction.remove_project:
                return ResourceAction.project_item_manage
            case BulkItemAction.add_tag | BulkItemAction.remove_tag:
                return ResourceAction.tag_use
            case BulkItemAction.delete_items:
                return ResourceAction.item_delete
            case _:
                assert_never(self)


async def apply_bulk_item_action(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_ids: list[UUID],
    action: BulkItemAction,
    *,
    project_id: UUID | None = None,
    tag_name: str = "",
    tag_id: UUID | None = None,
) -> None:
    try:
        action = BulkItemAction(action)
    except ValueError as error:
        raise ValidationFailure("unknown bulk action") from error
    items = await require_accessible_items(db, user, workspace_id, item_ids)

    cleanup_keys: tuple[str, ...] = ()
    match action:
        case BulkItemAction.add_project:
            if project_id is None:
                raise ValidationFailure("Project is required")
            try:
                await add_items_to_project(
                    db, user, workspace_id, project_id, [item.id for item in items]
                )
            except ResourceUnavailable as error:
                raise ValidationFailure("choose an editable project") from error
        case BulkItemAction.remove_project:
            if project_id is None:
                raise ValidationFailure("Project is required")
            await remove_items_from_project(
                db, user, workspace_id, project_id, [item.id for item in items]
            )
        case BulkItemAction.add_tag:
            await _add_tag_to_items(db, user, workspace_id, items, tag_name)
        case BulkItemAction.remove_tag:
            if tag_id is None:
                raise ValidationFailure("Tag is required")
            await _remove_tag_from_items(db, user, workspace_id, items, tag_id)
        case BulkItemAction.delete_items:
            await require_workspace_action(db, user, workspace_id, ResourceAction.item_delete)
            items, cleanup_keys = await _delete_items(db, workspace_id, items)
        case _:
            assert_never(action)

    record_event(
        db,
        user.id,
        action.audit_action,
        "item",
        None,
        detail={
            "item_ids": [item.id for item in items],
            **({"project_id": project_id} if action is BulkItemAction.remove_project else {}),
            **({"tag_id": tag_id} if action is BulkItemAction.remove_tag else {}),
        },
        workspace_id=workspace_id,
        project_id=project_id if action is BulkItemAction.remove_project else None,
        authorization_resource_action=action.resource_action.value,
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


async def _add_tag_to_items(
    db: AsyncSession, user: User, workspace_id: UUID, items: list[Item], tag_name: str
) -> None:
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
        raise TagConflict("tag associations changed concurrently; retry the bulk action") from error


async def _remove_tag_from_items(
    db: AsyncSession, user: User, workspace_id: UUID, items: list[Item], tag_id: UUID
) -> None:
    for item in sorted(items, key=lambda candidate: candidate.id):
        await require_item_action(db, user, workspace_id, item.id, ResourceAction.tag_use)
    # Protect the validated taxonomy root from deletion/merge until the
    # association changes commit. Item roots remain independent.
    tag = await db.scalar(
        select(Tag)
        .where(Tag.workspace_id == workspace_id, Tag.id == tag_id)
        .with_for_update(read=True)
    )
    if tag is None:
        raise ResourceUnavailable("Tag not found")
    for item_id in sorted({item.id for item in items}):
        await db.execute(
            delete(ItemTag).where(
                ItemTag.workspace_id == workspace_id,
                ItemTag.item_id == item_id,
                ItemTag.tag_id == tag_id,
            )
        )


async def _delete_items(
    db: AsyncSession, workspace_id: UUID, items: list[Item]
) -> tuple[list[Item], tuple[str, ...]]:
    # Lock every Item root in stable order before collecting child object keys. Upload and
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
    cleanup_keys = await delete_item_documents(db, workspace_id, requested_ids)
    for item in locked_items:
        await search_index(db).remove_item(db, item.id)
        await db.delete(item)
    return locked_items, cleanup_keys


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
