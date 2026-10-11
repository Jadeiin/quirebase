"""Suggest record-local contributor names without a shared Author identity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from inquiro.bibliography import Contributor as BibliographyContributor
from sqlalchemy import func, or_, select, true

from quirebase.models import Item

from ._json_queries import array_elements, contributor_name_parts
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
    candidates = items.with_only_columns(Item.authors).subquery()
    authors = array_elements(db, candidates.c.authors, objects=True)
    family, given, suffix = contributor_name_parts(authors.c.value)
    rows = await db.execute(
        select(family, given, suffix)
        .select_from(candidates.join(authors, true()))
        .where(
            or_(family.istartswith(term, autoescape=True), given.istartswith(term, autoescape=True))
        )
        .group_by(family, given, suffix)
        .order_by(family, func.coalesce(given, ""), func.coalesce(suffix, ""))
        .limit(limit)
    )
    return [
        {
            "last_name": last,
            "first_name": first,
            "suffix": name_suffix,
            "full_name": BibliographyContributor(
                " ".join(part for part in (last, name_suffix) if part), first
            ).display_name(),
        }
        for last, first, name_suffix in rows
    ]
