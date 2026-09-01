from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol

from quirebase.access.items import visible_items_query
from quirebase.audit import record_event

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
        detail={
            "fields": [clause.field for clause in clauses],
            "result_count": result_count,
        },
    )
    await db.commit()


async def get_accessible_item_identifiers(db: AsyncSession, user: User) -> set[tuple[str, str]]:
    identifiers_by_provider: set[tuple[str, str]] = set()
    for item in (await db.scalars(visible_items_query(user))).all():
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
