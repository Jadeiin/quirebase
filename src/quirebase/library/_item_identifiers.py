"""Persist canonical Identifier associations, including DOI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select, tuple_
from sqlalchemy.exc import IntegrityError

from quirebase.core.errors import ValidationFailure
from quirebase.models import ItemIdentifier

from ._metadata import normalize_identifier_pairs

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import Item


async def _replace_item_identifiers_many(
    db: AsyncSession,
    replacements: Sequence[tuple[Item, list[tuple[str, str]]]],
    *,
    replace: bool = True,
) -> list[ItemIdentifier]:
    prepared: list[tuple[Item, list[tuple[str, str]]]] = []
    claims: dict[tuple[UUID, str, str], UUID] = {}
    for item, pairs in replacements:
        normalized = normalize_identifier_pairs(pairs)
        for provider, value in normalized:
            identity = (item.workspace_id, provider, value)
            previous = claims.setdefault(identity, item.id)
            if previous != item.id:
                raise ValidationFailure(
                    "identifier is already assigned to another Item in this Workspace"
                )
        prepared.append((item, normalized))
    if await _claimed_by_other_items(db, claims):
        raise ValidationFailure("identifier is already assigned to another Item in this Workspace")
    links: list[ItemIdentifier] = []
    try:
        async with db.begin_nested():
            if replace:
                roots = [item.id for item, _ in prepared]
                for offset in range(0, len(roots), 500):
                    await db.execute(
                        delete(ItemIdentifier).where(
                            ItemIdentifier.item_id.in_(roots[offset : offset + 500])
                        )
                    )
            for item, pairs in prepared:
                for provider, value in pairs:
                    links.append(
                        ItemIdentifier(
                            workspace_id=item.workspace_id,
                            item_id=item.id,
                            provider=provider,
                            value=value,
                        )
                    )
            db.add_all(links)
            await db.flush()
    except IntegrityError:
        # A concurrent claimant can win after the preflight read. The unique
        # constraint is authoritative; recover the savepoint without retrying.
        if await _claimed_by_other_items(db, claims):
            raise ValidationFailure(
                "identifier is already assigned to another Item in this Workspace"
            ) from None
        raise
    return links


async def _claimed_by_other_items(
    db: AsyncSession, claims: dict[tuple[UUID, str, str], UUID]
) -> bool:
    identities = list(claims)
    for offset in range(0, len(identities), 500):
        rows = await db.execute(
            select(
                ItemIdentifier.workspace_id,
                ItemIdentifier.provider,
                ItemIdentifier.value,
                ItemIdentifier.item_id,
            ).where(
                tuple_(
                    ItemIdentifier.workspace_id, ItemIdentifier.provider, ItemIdentifier.value
                ).in_(identities[offset : offset + 500])
            )
        )
        if any(
            claims[workspace_id, provider, value] != item_id
            for workspace_id, provider, value, item_id in rows
        ):
            return True
    return False
