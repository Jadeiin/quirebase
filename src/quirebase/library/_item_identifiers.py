"""Persist canonical Identifier associations and their Item display cache."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import delete

from quirebase.core.errors import ValidationFailure
from quirebase.models import ItemIdentifier

from ._metadata import clean_identifier_value

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import Item


async def _replace_item_identifiers_many(
    db: AsyncSession,
    replacements: Sequence[tuple[Item, list[tuple[str, str]]]],
    *,
    replace: bool = True,
) -> list[ItemIdentifier]:
    prepared: list[tuple[Item, list[tuple[str, str]]]] = []
    for item, pairs in replacements:
        normalized: list[tuple[str, str]] = []
        for provider, value in pairs:
            provider = provider.strip().lower()
            value = clean_identifier_value(provider, value)
            if not provider or not value:
                continue
            if len(provider) > 40:
                raise ValidationFailure("identifier provider is too long")
            if len(value) > 500:
                raise ValidationFailure("identifier value is too long")
            normalized.append((provider, value))
        prepared.append((item, normalized))
    if replace:
        roots = [item.id for item, _ in prepared]
        for offset in range(0, len(roots), 500):
            await db.execute(
                delete(ItemIdentifier).where(
                    ItemIdentifier.item_id.in_(roots[offset : offset + 500])
                )
            )
    links: list[ItemIdentifier] = []
    for item, pairs in prepared:
        identifiers: dict[str, str] = {}
        doi: str | None = None
        for provider, value in pairs:
            if provider == "doi":
                doi = value
            else:
                links.append(ItemIdentifier(item_id=item.id, provider=provider, value=value))
                identifiers[provider] = value
        item.doi = doi
        item.identifiers = json.dumps(identifiers) if identifiers else None
    db.add_all(links)
    await db.flush()
    return links
