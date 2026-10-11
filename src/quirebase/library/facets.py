"""Bibliographic facets computed over the same visible candidates as Library Search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select, true

from quirebase.models import Item, ReferenceType

from ._json_queries import array_elements, contributor_name_parts
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
    suffix: str | None = None


@dataclass(frozen=True)
class KeywordFacet:
    value: str
    item_count: int


@dataclass(frozen=True)
class ReferenceTypeFacet:
    value: ReferenceType
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
    candidates = query.with_only_columns(
        Item.id, Item.authors, Item.keywords, Item.reference_type
    ).subquery()
    authors = array_elements(db, candidates.c.authors, objects=True)
    family, given, suffix = contributor_name_parts(authors.c.value)
    count = func.count(func.distinct(candidates.c.id)).label("item_count")
    author_rows = await db.execute(
        select(family, given, count, suffix)
        .select_from(candidates.join(authors, true()))
        .where(family.is_not(None), family != "")
        .group_by(family, given, suffix)
        .order_by(count.desc(), family, func.coalesce(given, ""), func.coalesce(suffix, ""))
        .limit(limit)
    )
    keywords = array_elements(db, candidates.c.keywords)
    keyword_rows = await db.execute(
        select(keywords.c.value, count)
        .select_from(candidates.join(keywords, true()))
        .where(keywords.c.value != "")
        .group_by(keywords.c.value)
        .order_by(count.desc(), keywords.c.value)
        .limit(limit)
    )
    type_rows = await db.execute(
        select(candidates.c.reference_type, count)
        .group_by(candidates.c.reference_type)
        .order_by(count.desc(), candidates.c.reference_type)
        .limit(limit)
    )
    return LibraryFacets(
        authors=tuple(AuthorFacet(*row) for row in author_rows),
        keywords=tuple(KeywordFacet(*row) for row in keyword_rows),
        reference_types=tuple(ReferenceTypeFacet(*row) for row in type_rows),
    )
