"""Suggest record-local contributor names without a shared Author identity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select, true

from quirebase.models import Item

from ._json_queries import array_elements, author_role, contributor_name_parts
from .catalog import LibraryFilter, _library_query

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import User


async def search_authors_typeahead(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    query: str,
    limit: int = 10,
    *,
    project: UUID | None = None,
) -> list[dict]:
    items = await _library_query(db, user, workspace_id, LibraryFilter(project=project))
    term = query.strip()
    if not term:
        return []
    candidates = items.with_only_columns(Item.work).subquery()
    authors = array_elements(db, candidates.c.work["contributors"], objects=True)
    family, given = contributor_name_parts(authors.c.value)
    rows = await db.execute(
        select(family, given)
        .select_from(candidates.join(authors, true()))
        .where(
            author_role(db, authors.c.value),
            or_(
                family.istartswith(term, autoescape=True), given.istartswith(term, autoescape=True)
            ),
        )
        .group_by(family, given)
        .order_by(family, func.coalesce(given, ""))
        .limit(limit)
    )
    return [
        {
            "last_name": last,
            "first_name": first,
            "full_name": ", ".join(part for part in (last, first) if part),
        }
        for last, first in rows
    ]
