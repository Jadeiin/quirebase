"""Library-owned repositories shared by its commands and read models."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import case, delete, select, update
from sqlalchemy.exc import IntegrityError

from quirebase.core.persistence import Repository, conflict_insert
from quirebase.models import (
    Author,
    ImportBatch,
    Item,
    ItemAuthor,
    ItemIdentifier,
    ItemRead,
    ItemTag,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
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

    async def advance_metadata_version(
        self,
        workspace_id: UUID,
        item_id: UUID,
        expected_version: int,
        actor_id: UUID,
        updated_at: datetime,
    ) -> int | None:
        return await self.replace_metadata_values(
            workspace_id,
            item_id,
            expected_version,
            {"updated_by": actor_id, "updated_at": updated_at},
        )


class ImportBatchRepository(Repository[ImportBatch]):
    model_type = ImportBatch


class ItemReadRepository(Repository[ItemRead]):
    model_type = ItemRead

    async def record_reading(
        self, workspace_id: UUID, user_id: UUID, item_id: UUID, read_at: datetime
    ) -> None:
        statement = conflict_insert(self.session, ItemRead).values(
            workspace_id=workspace_id, user_id=user_id, item_id=item_id, last_read_at=read_at
        )
        async with self.session.begin_nested():
            await self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=[ItemRead.user_id, ItemRead.item_id],
                    set_={
                        # Validate the supplied lineage on the update path too.
                        "workspace_id": statement.excluded.workspace_id,
                        "last_read_at": case(
                            (ItemRead.last_read_at < read_at, read_at), else_=ItemRead.last_read_at
                        ),
                    },
                )
            )


class AuthorRepository(Repository[Author]):
    model_type = Author

    async def _existing_identities(self, keys: set[str]) -> dict[str, Author]:
        found: dict[str, Author] = {}
        ordered = sorted(keys)
        for offset in range(0, len(ordered), 500):
            found.update({
                author.identity_key: author
                for author in await self.get_many(
                    Author.identity_key.in_(ordered[offset : offset + 500])
                )
            })
        return found

    async def resolve_identities(
        self, candidates: dict[str, tuple[str, str | None]]
    ) -> dict[str, Author]:
        resolved = await self._existing_identities(set(candidates))
        pending = set(candidates) - resolved.keys()
        while pending:
            try:
                async with self.session.begin_nested():
                    created: list[Author] = []
                    ordered = sorted(pending)
                    for offset in range(0, len(ordered), 500):
                        created.extend(
                            await self.add_many([
                                Author(
                                    identity_key=key,
                                    last_name=candidates[key][0],
                                    first_name=candidates[key][1],
                                )
                                for key in ordered[offset : offset + 500]
                            ])
                        )
            except IntegrityError:
                installed = await self._existing_identities(pending)
                if not installed:
                    raise
                resolved.update(installed)
                pending -= installed.keys()
            else:
                resolved.update({author.identity_key: author for author in created})
                break
        return resolved


class ItemAuthorRepository(Repository[ItemAuthor]):
    model_type = ItemAuthor


class ItemIdentifierRepository(Repository[ItemIdentifier]):
    model_type = ItemIdentifier


class ItemTagRepository(Repository[ItemTag]):
    model_type = ItemTag

    async def assign_many(
        self, workspace_id: UUID, item_ids: Sequence[UUID], tag_id: UUID
    ) -> set[UUID]:
        """Add links for authorized roots; report only this call's new links."""
        ordered = sorted(set(item_ids))
        created_ids: set[UUID] = set()
        if not ordered:
            return created_ids
        # Roll back every chunk if a non-identity constraint fails. The caller
        # still owns the surrounding transaction and any authorized root locks.
        async with self.session.begin_nested():
            for offset in range(0, len(ordered), 500):
                created_ids.update(
                    await self.session.scalars(
                        conflict_insert(self.session, ItemTag)
                        .values([
                            {"workspace_id": workspace_id, "item_id": item_id, "tag_id": tag_id}
                            for item_id in ordered[offset : offset + 500]
                        ])
                        .on_conflict_do_nothing(index_elements=[ItemTag.item_id, ItemTag.tag_id])
                        .returning(ItemTag.item_id)
                    )
                )
        return created_ids

    async def remove(self, workspace_id: UUID, item_id: UUID, tag_id: UUID) -> bool:
        return (
            await self.session.scalar(
                delete(ItemTag)
                .where(
                    ItemTag.workspace_id == workspace_id,
                    ItemTag.item_id == item_id,
                    ItemTag.tag_id == tag_id,
                )
                .returning(ItemTag.item_id)
            )
            is not None
        )

    async def move_tag_assignments(
        self, workspace_id: UUID, source_tag_id: UUID, target_tag_id: UUID
    ) -> None:
        """Move links after the command has locked both Tag roots in stable order."""
        item_ids = list(
            await self.session.scalars(
                select(ItemTag.item_id).where(
                    ItemTag.workspace_id == workspace_id, ItemTag.tag_id == source_tag_id
                )
            )
        )
        await self.assign_many(workspace_id, item_ids, target_tag_id)
        await self.session.execute(
            delete(ItemTag).where(
                ItemTag.workspace_id == workspace_id, ItemTag.tag_id == source_tag_id
            )
        )
