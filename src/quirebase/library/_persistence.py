"""Library-owned repositories shared by its commands and read models."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import update

from quirebase.core.persistence import Repository
from quirebase.models import Author, ImportBatch, Item, ItemAuthor, ItemIdentifier

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import InstrumentedAttribute


class ItemRepository(Repository[Item]):
    model_type = Item
    bibliography_load: ClassVar[list[list[InstrumentedAttribute]]] = [
        [Item.author_links, ItemAuthor.author]
    ]

    async def replace_metadata_values(
        self, workspace_id: UUID, item_id: UUID, expected_version: int, values: dict[str, object]
    ) -> int | None:
        return await self.session.scalar(
            update(Item)
            .where(
                Item.workspace_id == workspace_id,
                Item.id == item_id,
                Item.version == expected_version,
            )
            .values(**values, version=Item.version + 1)
            .returning(Item.version)
        )


class ImportBatchRepository(Repository[ImportBatch]):
    model_type = ImportBatch


class AuthorRepository(Repository[Author]):
    model_type = Author


class ItemAuthorRepository(Repository[ItemAuthor]):
    model_type = ItemAuthor


class ItemIdentifierRepository(Repository[ItemIdentifier]):
    model_type = ItemIdentifier
