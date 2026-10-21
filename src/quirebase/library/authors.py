"""Suggest record-local contributor names without a shared Author identity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select, true

from quirebase.models import Item

from ._json_queries import (
    _contributor_display_name,
    _grouped_contributor_name,
    array_elements,
    author_role,
    contributor_name_parts,
)
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
    names = (
        select(
            family.label("last_name"),
            given.label("first_name"),
            _contributor_display_name(authors.c.value).label("display_name"),
        )
        .select_from(candidates.join(authors, true()))
        .where(family.is_not(None), family != "", author_role(db, authors.c.value))
        .subquery()
    )
    family, given = names.c.last_name, names.c.first_name
    full_name = _grouped_contributor_name(family, given, names.c.display_name)
    grouped = (
        select(family, given, full_name.label("full_name"))
        .group_by(family, given)
        .having(full_name != "")
        .subquery()
    )
    rows = await db.execute(
        select(grouped)
        .where(
            or_(
                grouped.c.last_name.istartswith(term, autoescape=True),
                grouped.c.first_name.istartswith(term, autoescape=True),
                grouped.c.full_name.istartswith(term, autoescape=True),
            )
        )
        .order_by(grouped.c.last_name, func.coalesce(grouped.c.first_name, ""))
        .limit(limit)
    )
    return [
        {
            "last_name": last,
            "first_name": first,
            "full_name": full_name,
        }
        for last, first, full_name in rows
    ]
