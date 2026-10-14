"""Bibliographic facets computed over the same visible candidates as Library Search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select, true

from quirebase.models import Item

from ._json_queries import array_elements, author_role, contributor_name_parts
from .catalog import LibraryFilter, _library_query

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import User


@dataclass(frozen=True)
class AuthorFacet:
    last_name: str
    first_name: str | None
    item_count: int


@dataclass(frozen=True)
class KeywordFacet:
    value: str
    item_count: int


@dataclass(frozen=True)
class ReferenceTypeFacet:
    value: str
    item_count: int


@dataclass(frozen=True)
class LibraryFacets:
    authors: tuple[AuthorFacet, ...]
    keywords: tuple[KeywordFacet, ...]
    reference_types: tuple[ReferenceTypeFacet, ...]


async def get_library_facets(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    filters: LibraryFilter = LibraryFilter(),
    *,
    limit: int = 50,
) -> LibraryFacets:
    query = await _library_query(db, user, workspace_id, filters)
    candidates = query.with_only_columns(Item.id, Item.work).subquery()
    authors = array_elements(db, candidates.c.work["contributors"], objects=True)
    family, given = contributor_name_parts(authors.c.value)
    count = func.count(func.distinct(candidates.c.id)).label("item_count")
    author_rows = await db.execute(
        select(family, given, count)
        .select_from(candidates.join(authors, true()))
        .where(family.is_not(None), family != "", author_role(db, authors.c.value))
        .group_by(family, given)
        .order_by(count.desc(), family, func.coalesce(given, ""))
        .limit(limit)
    )
    keywords = array_elements(db, candidates.c.work["subjects"], objects=True)
    subject = keywords.c.value["subject"].as_string()
    keyword_rows = await db.execute(
        select(subject, count)
        .select_from(candidates.join(keywords, true()))
        .where(subject != "")
        .group_by(subject)
        .order_by(count.desc(), subject)
        .limit(limit)
    )
    reference_type = candidates.c.work["type"].as_string()
    type_rows = await db.execute(
        select(reference_type, count)
        .group_by(reference_type)
        .order_by(count.desc(), reference_type)
        .limit(limit)
    )
    return LibraryFacets(
        authors=tuple(AuthorFacet(*row) for row in author_rows),
        keywords=tuple(KeywordFacet(*row) for row in keyword_rows),
        reference_types=tuple(ReferenceTypeFacet(*row) for row in type_rows),
    )
