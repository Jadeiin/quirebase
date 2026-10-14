from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from inquiro.identifiers import canonical_doi
from inquiro.work import work_doi
from sqlalchemy import select, update

from quirebase.access import ResourceAction
from quirebase.access.items import require_editable_item
from quirebase.audit import record_event
from quirebase.core.errors import ResourceUnavailable, VersionConflict
from quirebase.documents.pdf import first_doi_from_text
from quirebase.library.providers import lookup_candidate
from quirebase.library.workflows import request_item_tag_recommendation
from quirebase.models import FileRevision, Item, User
from quirebase.search import search_index

from ._metadata import candidate_write, generate_citation_key, validate_citation_key

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.core.config import Settings


async def rescan_pdf_doi(
    db: AsyncSession, user: User, workspace_id: UUID, item_id: UUID
) -> str | None:
    # Scan the immutable extracted text without holding an Item lock. Re-authorize and lock the
    # canonical Item only after a DOI candidate is found, immediately before mutating identifiers.
    await require_editable_item(db, user, workspace_id, item_id)
    revisions = list(
        (
            await db.scalars(
                select(FileRevision)
                .where(
                    FileRevision.workspace_id == workspace_id,
                    FileRevision.item_id == item_id,
                )
                .order_by(FileRevision.created_at.desc())
            )
        ).all()
    )
    for rev in revisions:
        if rev.full_text:
            found_doi = first_doi_from_text(rev.full_text)
            if found_doi:
                await require_editable_item(db, user, workspace_id, item_id)
                # key_share=True without read=True emits FOR NO KEY UPDATE on PostgreSQL:
                # serialize Work replacements and refresh any snapshot read before the wait.
                item = await db.scalar(
                    select(Item)
                    .where(Item.id == item_id, Item.workspace_id == workspace_id)
                    .execution_options(populate_existing=True)
                    .with_for_update(key_share=True)
                )
                if item is None:
                    raise ResourceUnavailable("item not found")
                # A manually supplied DOI takes precedence over scanner output.
                if doi := work_doi(item.work):
                    return doi
                found_doi = canonical_doi(found_doi)
                work = deepcopy(item.work)
                work.setdefault("identifiers", []).append({
                    "identifier_type": "DOI",
                    "identifier": found_doi,
                })
                item.work = candidate_write(item, work, merge=False)["work"]
                item.updated_by = user.id
                item.updated_at = datetime.now(UTC)
                item.version += 1
                await db.flush()
                await search_index(db).index_item(db, item_id)
                record_event(
                    db,
                    user.id,
                    "item.rescan_doi",
                    "item",
                    item_id,
                    workspace_id=item.workspace_id,
                    authorization_resource_action=ResourceAction.item_update.value,
                )
                await db.commit()
                return found_doi
    return None


async def _merge_metadata_work(
    db: AsyncSession,
    user: User,
    item: Item,
    work: dict,
) -> Item:
    item = await require_editable_item(db, user, item.workspace_id, item.id)
    write = candidate_write(item, work, merge=True)
    item.work = write["work"]
    if not item.citation_key:
        item.citation_key = generate_citation_key(item)
    await db.flush()
    return item


async def _sync_metadata_from_upstream(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    expected_version: int,
    provider: str,
    uid_value: str,
    settings: Settings | None = None,
) -> Item:
    user_id = user.id
    item = await require_editable_item(db, user, workspace_id, item_id)
    previous_generated_key = generate_citation_key(item)
    previous_key = item.citation_key

    from quirebase.operations.settings import get_effective_settings_model

    effective_settings = settings or await get_effective_settings_model(db)
    # Do not keep the read transaction open while waiting on the provider.
    # Re-read the item and enforce its expected version after the external call.
    await db.rollback()
    record = await lookup_candidate(uid_value, provider, effective_settings)
    reloaded_user = await db.get(User, user_id)
    if reloaded_user is None or not reloaded_user.active:
        raise ResourceUnavailable("user not available")
    user = reloaded_user
    item = await require_editable_item(db, user, workspace_id, item_id)
    version = await db.scalar(
        update(Item)
        .where(
            Item.workspace_id == workspace_id, Item.id == item_id, Item.version == expected_version
        )
        .values(updated_by=user.id, updated_at=datetime.now(UTC), version=Item.version + 1)
        .returning(Item.version)
    )
    if version is None:
        await db.rollback()
        current = await db.get(Item, item_id)
        raise VersionConflict(current.version if current else None)

    await db.refresh(item)
    await _merge_metadata_work(
        db,
        user,
        item,
        record.work,
    )

    # Upstream changes commonly alter the title, first author or year. Keep a
    # key that was generated from the previous metadata in sync, while leaving
    # an explicitly edited key untouched.
    if not previous_key or previous_key == previous_generated_key:
        regenerated_key = generate_citation_key(item)
        if regenerated_key != item.citation_key:
            item.citation_key = regenerated_key

    await db.flush()

    await search_index(db).index_item(db, item_id)
    await request_item_tag_recommendation(
        db,
        item_id,
        workspace_id=item.workspace_id,
        actor_id=user.id,
        force=True,
    )
    record_event(
        db,
        user.id,
        "item.sync_upstream",
        "item",
        item_id,
        detail={
            "provider": record.provider,
            "lookup_provider": provider,
            "old_citation_key": previous_key,
            "new_citation_key": item.citation_key,
            "citation_key_updated": bool(
                previous_key != item.citation_key
                and (not previous_key or previous_key == previous_generated_key)
            ),
        },
        workspace_id=item.workspace_id,
        authorization_resource_action=ResourceAction.item_update.value,
    )
    await db.commit()
    return item


async def sync_metadata_from_upstream(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    expected_version: int,
    provider: str,
    uid_value: str,
    settings: Settings | None = None,
) -> Item:
    try:
        return await _sync_metadata_from_upstream(
            db,
            user,
            workspace_id,
            item_id,
            expected_version,
            provider,
            uid_value,
            settings,
        )
    except Exception:
        await db.rollback()
        raise


async def _create_items_from_candidates(
    db: AsyncSession, workspace_id: UUID, actor_id: UUID, records: Sequence[dict]
) -> list[Item]:
    items = []
    for record in records:
        item = Item(work={}, workspace_id=workspace_id, created_by=actor_id)
        item.work = candidate_write(item, record["work"], merge=False)["work"]
        item.citation_key = validate_citation_key(record.get("citation_key"))
        items.append(item)
    db.add_all(items)
    await db.flush()
    for item in items:
        if not item.citation_key:
            item.citation_key = generate_citation_key(item)
    await db.flush()
    return items
