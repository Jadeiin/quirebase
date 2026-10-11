from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from inquiro.metadata import clean_identifier_value
from sqlalchemy import select, tuple_

from quirebase.access import ResourceAction, require_workspace_action, workspace_items_query
from quirebase.audit import record_event
from quirebase.models import Item, ItemIdentifier

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import User


class SearchClauseView(Protocol):
    @property
    def field(self) -> str: ...


async def record_discovery_search_audit(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
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
    db: AsyncSession, user: User, workspace_id: UUID
) -> set[tuple[str, str]]:
    context = await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    candidates = workspace_items_query(context).with_only_columns(Item.id).subquery()
    identifier_rows = await db.execute(
        select(ItemIdentifier.provider, ItemIdentifier.value).where(
            ItemIdentifier.item_id.in_(select(candidates.c.id))
        )
    )
    return set(identifier_rows.tuples())


async def get_matching_accessible_item_identifiers(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    candidates: set[tuple[str, str]],
) -> set[tuple[str, str]]:
    """Return accessible identifiers that occur in one Provider result page."""
    context = await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    normalized = {
        (provider.strip().lower(), clean_identifier_value(provider, value))
        for provider, value in candidates
        if provider and value
    }
    if not normalized:
        return set()

    visible_ids = workspace_items_query(context).with_only_columns(Item.id).subquery()
    identifier_rows = await db.execute(
        select(ItemIdentifier.provider, ItemIdentifier.value).where(
            ItemIdentifier.item_id.in_(select(visible_ids.c.id)),
            tuple_(ItemIdentifier.provider, ItemIdentifier.value).in_(normalized),
        )
    )
    return set(identifier_rows.tuples())
