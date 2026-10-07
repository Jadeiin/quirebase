"""Persist Item metadata aggregates inside the owning command's transaction."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from quirebase.core.persistence import Service
from quirebase.models import Item, ItemIdentifier

from ._item_identifiers import _replace_item_identifiers_many
from ._metadata import (
    ItemMetadata,
    MetadataWrite,
    candidate_write,
    generate_bibtex_key,
    metadata_write,
)
from ._persistence import ItemIdentifierRepository, ItemRepository
from .authors import _replace_item_authors_many

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class ItemService(Service[Item]):
    repository_type = ItemRepository
    repository: ItemRepository

    def __init__(self, session: AsyncSession, **kwargs: Any) -> None:
        super().__init__(session, **kwargs)
        self._db = session

    async def create_from_metadata(
        self, workspace_id: UUID, actor_id: UUID, metadata: ItemMetadata
    ) -> Item:
        write = metadata_write(metadata)
        item = await self.create(
            write.values | {"workspace_id": workspace_id, "created_by": actor_id}
        )
        await self._write_links([(item, write)], replace=False)
        return item

    async def replace_metadata(
        self, item: Item, actor_id: UUID, expected_version: int, metadata: ItemMetadata
    ) -> int | None:
        write = metadata_write(metadata)
        version = await self.repository.replace_metadata_values(
            item.workspace_id,
            item.id,
            expected_version,
            write.values | {"updated_by": actor_id, "updated_at": datetime.now(UTC)},
        )
        if version is not None:
            await self._write_links([(item, write)])
        return version

    async def create_many_from_candidates(
        self, workspace_id: UUID, actor_id: UUID, records: Sequence[dict]
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
        items = list(await self.create_many([item for item, _ in prepared]))
        await self._write_links(prepared, replace=False)
        for item in items:
            if not item.bibtex_id:
                item.bibtex_id = generate_bibtex_key(item)
        await self._db.flush()
        return items

    async def merge_candidate(
        self,
        item: Item,
        record: dict,
        *,
        merge: bool = True,
        forced_identifiers: dict[str, str] | None = None,
    ) -> Item:
        existing = (
            {
                link.provider: link.value
                for link in await ItemIdentifierRepository(session=self._db).get_many(
                    ItemIdentifier.item_id == item.id
                )
            }
            if merge
            else {}
        )
        write = candidate_write(
            item,
            record,
            merge=merge,
            existing_identifiers=existing,
            forced_identifiers=forced_identifiers,
        )
        for name, value in write.values.items():
            setattr(item, name, value)
        await self._write_links([(item, write)])
        if not item.bibtex_id:
            item.bibtex_id = generate_bibtex_key(item)
        await self._db.flush()
        return item

    async def _write_links(
        self, prepared: Sequence[tuple[Item, MetadataWrite]], *, replace: bool = True
    ) -> None:
        contributors: list[tuple[Item, str, list[dict]]] = []
        for item, write in prepared:
            if write.authors is not None:
                contributors.append((item, "author", write.authors))
            if write.editors is not None:
                contributors.append((item, "editor", write.editors))
        if contributors:
            await _replace_item_authors_many(self._db, contributors, replace=replace)
        identifiers = [
            (item, write.identifiers) for item, write in prepared if write.identifiers is not None
        ]
        if identifiers:
            await _replace_item_identifiers_many(self._db, identifiers, replace=replace)

    async def get_bibliography(self) -> list[Item]:
        return list(
            await self.get_many(
                load=ItemRepository.bibliography_load,
                order_by=[("updated_at", True), ("id", False)],
            )
        )
