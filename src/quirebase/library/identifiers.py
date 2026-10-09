from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from inquiro.identifiers import DOI_PATTERN, normalize_doi
from inquiro.models import CandidateRecord
from sqlalchemy import select, update

from quirebase.access import ResourceAction, require_workspace_action
from quirebase.access.items import require_editable_item
from quirebase.audit import record_event
from quirebase.core.errors import ResourceUnavailable, VersionConflict
from quirebase.documents.pdf import first_doi_from_text
from quirebase.library.providers import candidate_record_values, lookup_candidate
from quirebase.library.workflows import request_item_tag_recommendation
from quirebase.models import FileRevision, Item, ItemIdentifier, User
from quirebase.search import search_index

from ._item_identifiers import _replace_item_identifiers_many
from ._metadata import MetadataWrite, candidate_write, generate_bibtex_key
from .item_metadata import _write_item_links

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.core.config import Settings


async def set_item_identifiers(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    id_pairs: list[tuple[str, str]],
) -> list[ItemIdentifier]:
    item = await require_editable_item(db, user, workspace_id, item_id)
    return await _replace_item_identifiers_many(db, [(item, id_pairs)])


async def get_item_identifiers(db: AsyncSession, item_id: UUID) -> list[ItemIdentifier]:
    return list(
        (await db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item_id))).all()
    )


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
                item = await db.scalar(
                    select(Item)
                    .where(Item.id == item_id, Item.workspace_id == workspace_id)
                    .execution_options(populate_existing=True)
                    .with_for_update(key_share=True)
                )
                if item is None:
                    raise ResourceUnavailable("item not found")
                # A manually supplied DOI takes precedence over scanner output.
                if item.doi:
                    return item.doi
                existing_pairs = [
                    (ident.provider, ident.value)
                    for ident in await get_item_identifiers(db, item_id)
                    if ident.provider != "doi"
                ]
                existing_pairs.append(("doi", found_doi))
                await _replace_item_identifiers_many(db, [(item, existing_pairs)])
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


async def apply_metadata_record(
    db: AsyncSession,
    user: User,
    item: Item,
    record: CandidateRecord | dict,
    *,
    merge: bool = False,
    forced_identifiers: dict[str, str] | None = None,
) -> Item:
    item = await require_editable_item(db, user, item.workspace_id, item.id)
    values = candidate_record_values(record) if isinstance(record, CandidateRecord) else record
    existing = (
        {
            link.provider: link.value
            for link in await db.scalars(
                select(ItemIdentifier).where(ItemIdentifier.item_id == item.id)
            )
        }
        if merge
        else {}
    )
    write = candidate_write(
        item,
        values,
        merge=merge,
        existing_identifiers=existing,
        forced_identifiers=forced_identifiers,
    )
    for name, value in write.values.items():
        setattr(item, name, value)
    await _write_item_links(db, [(item, write)])
    if not item.bibtex_id:
        item.bibtex_id = generate_bibtex_key(item)
    await db.flush()
    return item


async def create_item_from_metadata_record(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    record: CandidateRecord | dict,
) -> Item:
    """Create an imported Item and enqueue its initial Tag recommendation."""
    await require_workspace_action(db, user, workspace_id, ResourceAction.item_create)
    values = candidate_record_values(record) if isinstance(record, CandidateRecord) else record
    items = await _create_items_from_candidates(db, workspace_id, user.id, [values])
    item = items[0]
    await request_item_tag_recommendation(db, item.id, workspace_id=workspace_id, actor_id=user.id)
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
    previous_generated_key = generate_bibtex_key(item)
    previous_key = item.bibtex_id

    from quirebase.operations.settings import get_effective_settings_model

    effective_settings = settings or await get_effective_settings_model(db)
    # Do not keep the read transaction open while waiting on the provider.
    # Re-read the item and enforce its expected version after the external call.
    await db.rollback()
    record = await lookup_candidate(uid_value, provider, effective_settings)
    upstream_identifier = record.identifier
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
    normalized_upstream_value = normalize_doi(upstream_identifier.value)
    forced_identifiers = (
        {upstream_identifier.provider: upstream_identifier.value}
        if upstream_identifier.provider
        and upstream_identifier.value
        and not DOI_PATTERN.fullmatch(normalized_upstream_value)
        else None
    )
    await apply_metadata_record(
        db,
        user,
        item,
        record,
        merge=True,
        forced_identifiers=forced_identifiers,
    )
    # The item was eagerly loaded before its link rows were replaced. Reload
    # those collections explicitly so callers never observe the stale identity-
    # map snapshot or trigger lazy I/O after this async operation returns.
    await db.refresh(item, ["author_links", "identifier_links"])
    for link in item.author_links:
        await db.refresh(link, ["author"])

    # Upstream changes commonly alter the title, first author or year. Keep a
    # key that was generated from the previous metadata in sync, while leaving
    # an explicitly edited key untouched.
    if not previous_key or previous_key == previous_generated_key:
        regenerated_key = generate_bibtex_key(item)
        if regenerated_key != item.bibtex_id:
            item.bibtex_id = regenerated_key

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
            "provider": upstream_identifier.provider,
            "old_bibtex_key": previous_key,
            "new_bibtex_key": item.bibtex_id,
            "bibtex_key_updated": bool(
                previous_key != item.bibtex_id
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
    prepared: list[tuple[Item, MetadataWrite]] = []
    for record in records:
        item = Item(title="Untitled", workspace_id=workspace_id, created_by=actor_id)
        write = candidate_write(item, record, merge=False, existing_identifiers={})
        for name, value in write.values.items():
            setattr(item, name, value)
        prepared.append((item, write))
    if not prepared:
        return []
    items = [item for item, _ in prepared]
    db.add_all(items)
    await db.flush()
    await _write_item_links(db, prepared, replace=False)
    for item in items:
        if not item.bibtex_id:
            item.bibtex_id = generate_bibtex_key(item)
    await db.flush()
    return items
