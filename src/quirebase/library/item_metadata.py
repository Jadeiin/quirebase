"""Create and revise one Item's bibliographic metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, update

from quirebase.access import ResourceAction, require_workspace_action
from quirebase.access.items import require_editable_item
from quirebase.audit import record_event
from quirebase.core.errors import ResourceUnavailable, VersionConflict
from quirebase.library.workflows import request_item_tag_recommendation
from quirebase.models import Item
from quirebase.search import search_index

from ._item_identifiers import _replace_item_identifiers_many
from ._metadata import (
    ItemMetadata,
    ItemWriteResult,
    MetadataWrite,
    generate_bibtex_key,
    metadata_write,
)
from .authors import _replace_item_authors_many

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import User


async def _create_item(
    db: AsyncSession,
    actor: User,
    workspace_id: UUID,
    metadata: ItemMetadata,
) -> ItemWriteResult:
    context = await require_workspace_action(db, actor, workspace_id, ResourceAction.item_create)
    write = metadata_write(metadata)
    item = Item(**write.values, workspace_id=workspace_id, created_by=actor.id)
    db.add(item)
    await db.flush()
    await _write_item_links(db, [(item, write)], replace=False)
    await search_index(db).index_item(db, item.id)
    await request_item_tag_recommendation(db, item.id, workspace_id=workspace_id, actor_id=actor.id)
    record_event(
        db,
        actor.id,
        "item.create",
        "item",
        item.id,
        workspace_id=workspace_id,
        authorization_role=context.role.value,
        authorization_resource_action=ResourceAction.item_create.value,
    )
    await db.commit()
    return ItemWriteResult(item_id=item.id, version=item.version)


async def create_item(
    db: AsyncSession,
    actor: User,
    workspace_id: UUID,
    metadata: ItemMetadata,
) -> ItemWriteResult:
    try:
        return await _create_item(db, actor, workspace_id, metadata)
    except Exception:
        await db.rollback()
        raise


async def _revise_item_metadata(
    db: AsyncSession,
    actor: User,
    workspace_id: UUID,
    item_id: UUID,
    expected_version: int,
    metadata: ItemMetadata,
) -> ItemWriteResult:
    actor_id = actor.id
    item = await require_editable_item(db, actor, workspace_id, item_id)
    write = metadata_write(metadata)
    version = await db.scalar(
        update(Item)
        .where(
            Item.workspace_id == workspace_id,
            Item.id == item_id,
            Item.version == expected_version,
        )
        .values(
            **write.values,
            updated_by=actor_id,
            updated_at=datetime.now(UTC),
            version=Item.version + 1,
        )
        .returning(Item.version)
    )
    if version is None:
        await db.rollback()
        current = await db.get(Item, item_id)
        raise VersionConflict(current.version if current else None)

    await _write_item_links(db, [(item, write)])

    # The bulk UPDATE does not reliably populate every value used by the search
    # projection. Refresh only the mutated aggregate; expiring the whole session
    # also expires the caller's User and invites implicit async ORM I/O later.
    await db.refresh(item)
    await search_index(db).index_item(db, item_id)
    await request_item_tag_recommendation(
        db,
        item_id,
        workspace_id=workspace_id,
        actor_id=actor_id,
        force=True,
    )
    record_event(
        db,
        actor_id,
        "item.update",
        "item",
        item_id,
        detail={"version": version},
        workspace_id=workspace_id,
        authorization_resource_action=ResourceAction.item_update.value,
    )
    await db.commit()
    return ItemWriteResult(item_id=item_id, version=version)


async def revise_item_metadata(
    db: AsyncSession,
    actor: User,
    workspace_id: UUID,
    item_id: UUID,
    expected_version: int,
    metadata: ItemMetadata,
) -> ItemWriteResult:
    try:
        return await _revise_item_metadata(
            db, actor, workspace_id, item_id, expected_version, metadata
        )
    except Exception:
        await db.rollback()
        raise


async def _regenerate_bibtex_key(
    db: AsyncSession,
    actor: User,
    workspace_id: UUID,
    item_id: UUID,
) -> ItemWriteResult:
    actor_id = actor.id
    await require_editable_item(db, actor, workspace_id, item_id)
    item = await db.scalar(
        select(Item)
        .where(Item.id == item_id, Item.workspace_id == workspace_id)
        .execution_options(populate_existing=True)
        .with_for_update(key_share=True)
    )
    if item is None:
        raise ResourceUnavailable("item not found")
    key = generate_bibtex_key(item)
    item.bibtex_id = key
    item.updated_by = actor_id
    item.updated_at = datetime.now(UTC)
    item.version += 1
    version = item.version
    await db.flush()
    await search_index(db).index_item(db, item_id)
    record_event(
        db,
        actor_id,
        "item.bibtex_key.regenerate",
        "item",
        item_id,
        detail={"version": version},
        workspace_id=workspace_id,
        authorization_resource_action=ResourceAction.item_update.value,
    )
    await db.commit()
    return ItemWriteResult(item_id=item_id, version=version)


async def regenerate_bibtex_key(
    db: AsyncSession,
    actor: User,
    workspace_id: UUID,
    item_id: UUID,
) -> ItemWriteResult:
    try:
        return await _regenerate_bibtex_key(db, actor, workspace_id, item_id)
    except Exception:
        await db.rollback()
        raise


async def _write_item_links(
    db: AsyncSession, prepared: Sequence[tuple[Item, MetadataWrite]], *, replace: bool = True
) -> None:
    contributors: list[tuple[Item, str, list[dict]]] = []
    for item, write in prepared:
        if write.authors is not None:
            contributors.append((item, "author", write.authors))
        if write.editors is not None:
            contributors.append((item, "editor", write.editors))
    if contributors:
        await _replace_item_authors_many(db, contributors, replace=replace)
    identifiers = [
        (item, write.identifiers) for item, write in prepared if write.identifiers is not None
    ]
    if identifiers:
        await _replace_item_identifiers_many(db, identifiers, replace=replace)
