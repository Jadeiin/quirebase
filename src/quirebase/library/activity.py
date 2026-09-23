from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import func, select, tuple_

from quirebase.access.items import visible_items_query
from quirebase.audit import record_event
from quirebase.models import Item, ItemIdentifier

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import User


class SearchClauseView(Protocol):
    @property
    def field(self) -> str: ...


async def record_discovery_search_audit(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    provider: str,
    clauses: Sequence[SearchClauseView],
    result_count: int,
) -> None:
    record_event(
        db,
        user.id,
        "metadata.search",
        "provider",
        provider,
        workspace_id=workspace_id,
        detail={
            "fields": [clause.field for clause in clauses],
            "result_count": result_count,
        },
    )
    await db.commit()


async def get_accessible_item_identifiers(
    db: AsyncSession, user: User, workspace_id: str
) -> set[tuple[str, str]]:
    identifiers_by_provider: set[tuple[str, str]] = set()
    for item in (await db.scalars(visible_items_query(workspace_id))).all():
        if item.doi:
            identifiers_by_provider.add(("doi", item.doi.casefold()))
        try:
            identifiers = json.loads(item.identifiers or "{}")
        except json.JSONDecodeError:
            identifiers = {}
        for key, value in identifiers.items():
            if value:
                identifiers_by_provider.add((str(key), str(value).casefold()))
    return identifiers_by_provider


async def get_matching_accessible_item_identifiers(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    candidates: set[tuple[str, str]],
) -> set[tuple[str, str]]:
    """Return accessible identifiers that occur in one Provider result page."""
    normalized = {
        (provider.casefold(), value.casefold())
        for provider, value in candidates
        if provider and value
    }
    if not normalized:
        return set()

    visible_ids = visible_items_query(workspace_id).with_only_columns(Item.id).subquery()
    matched: set[tuple[str, str]] = set()

    doi_values = {value for provider, value in normalized if provider == "doi"}
    if doi_values:
        rows = await db.scalars(
            select(func.lower(Item.doi)).where(
                Item.id.in_(select(visible_ids.c.id)),
                func.lower(Item.doi).in_(doi_values),
            )
        )
        matched.update(("doi", value) for value in rows if value)

    upstream = {(provider, value) for provider, value in normalized if provider != "doi"}
    if upstream:
        identifier_rows = await db.execute(
            select(func.lower(ItemIdentifier.provider), func.lower(ItemIdentifier.value)).where(
                ItemIdentifier.item_id.in_(select(visible_ids.c.id)),
                tuple_(
                    func.lower(ItemIdentifier.provider),
                    func.lower(ItemIdentifier.value),
                ).in_(upstream),
            )
        )
        matched.update((provider, value) for provider, value in identifier_rows)

    return matched
