"""Bibliographic facets computed from the current Library result page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select, true

from quirebase.core.errors import ValidationFailure
from quirebase.models import Item

from ._json_queries import (
    _contributor_display_name,
    _grouped_contributor_name,
    array_elements,
    author_role,
    contributor_name_parts,
)
from .catalog import LibraryFilter, _library_query, _ordered_library_query

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import User


@dataclass(frozen=True)
class AuthorFacet:
    last_name: str
    first_name: str | None
    full_name: str
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
    limit: int = 25,
    offset: int = 0,
    sort: Literal["updated", "created", "title", "published", "publication", "author"] = "updated",
    direction: Literal["asc", "desc"] | None = None,
) -> LibraryFacets:
    query = await _library_query(db, user, workspace_id, filters)
    if not 1 <= limit <= 100 or offset < 0:
        raise ValidationFailure("invalid Library page")
    candidates = (
        _ordered_library_query(db, query, sort, direction)
        .with_only_columns(Item.id, Item.work)
        .limit(limit)
        .offset(offset)
        .subquery()
    )
    authors = array_elements(db, candidates.c.work["contributors"], objects=True)
    family, given = contributor_name_parts(authors.c.value)
    names = (
        select(
            candidates.c.id.label("item_id"),
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
    count = func.count(func.distinct(names.c.item_id)).label("item_count")
    author_rows = await db.execute(
        select(family, given, full_name, count)
        .group_by(family, given)
        .having(full_name != "")
        .order_by(count.desc(), family, func.coalesce(given, ""))
    )
    count = func.count(func.distinct(candidates.c.id)).label("item_count")
    keywords = array_elements(db, candidates.c.work["subjects"], objects=True)
    subject = keywords.c.value["subject"].as_string()
    keyword_rows = await db.execute(
        select(subject, count)
        .select_from(candidates.join(keywords, true()))
        .where(subject != "")
        .group_by(subject)
        .order_by(count.desc(), subject)
    )
    count = func.count(func.distinct(candidates.c.id)).label("item_count")
    reference_type = candidates.c.work["type"].as_string()
    type_rows = await db.execute(
        select(reference_type, count)
        .group_by(reference_type)
        .order_by(count.desc(), reference_type)
    )
    return LibraryFacets(
        authors=tuple(AuthorFacet(*row) for row in author_rows),
        keywords=tuple(KeywordFacet(*row) for row in keyword_rows),
        reference_types=tuple(ReferenceTypeFacet(*row) for row in type_rows),
    )
