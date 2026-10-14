"""SQLAlchemy expressions for querying the two supported JSON array dialects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Text, case, column, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from quirebase.models import Item

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement
    from sqlalchemy.sql.selectable import FromClause


def array_elements(db: AsyncSession, array: Any, *, objects: bool = False) -> FromClause:
    """Expand a JSON array, using LATERAL only where the database requires it."""
    if db.get_bind().dialect.name == "postgresql":
        function = func.jsonb_array_elements if objects else func.jsonb_array_elements_text
        return function(array).table_valued(column("value", JSONB if objects else Text)).lateral()
    return func.json_each(array).table_valued(column("value", JSON if objects else Text))


def contributor_name_parts(value: Any) -> tuple[Any, Any]:
    person = value["person"]
    organization = value["organization"]
    is_person = value["type"].as_string() == "Person"
    family_name = func.nullif(person["family_name"].as_string(), "")
    family = case(
        (
            is_person,
            func.coalesce(
                family_name,
                func.nullif(person["name"].as_string(), ""),
                person["given_name"].as_string(),
            ),
        ),
        else_=organization["name"].as_string(),
    )
    # A name without a family component is one display value, not a repeated
    # family/given pair. Facet selection uses this same projection.
    given = case(
        (is_person & family_name.is_not(None), func.nullif(person["given_name"].as_string(), "")),
        else_=None,
    )
    return family, given


def author_role(db: AsyncSession, value: Any) -> ColumnElement[bool]:
    roles = array_elements(db, value["roles"])
    return select(1).select_from(roles).where(roles.c.value == "Author").exists()


def author_condition(
    db: AsyncSession,
    *,
    text: str = "",
    last_name: str | None = None,
    first_name: str | None = None,
) -> ColumnElement[bool]:
    authors = array_elements(db, Item.work["contributors"], objects=True)
    family, given = contributor_name_parts(authors.c.value)
    display = case(
        (
            authors.c.value["type"].as_string() == "Person",
            authors.c.value["person"]["name"].as_string(),
        ),
        else_=authors.c.value["organization"]["name"].as_string(),
    )
    query = select(1).select_from(authors).where(author_role(db, authors.c.value))
    if last_name is not None:
        # Facet values preserve Work strings. Exact selection must compare the
        # returned value verbatim rather than normalize only the request.
        query = query.where(family == last_name)
        if first_name is not None:
            query = query.where(given == first_name if first_name != "" else given.is_(None))
    if text:
        full_name = family + ", " + func.coalesce(given, "")
        query = query.where(
            or_(
                display.icontains(text, autoescape=True),
                family.icontains(text, autoescape=True),
                given.icontains(text, autoescape=True),
                full_name.icontains(text, autoescape=True),
            )
        )
    predicate: ColumnElement[bool] = query.correlate(Item).exists()
    return predicate


def keyword_condition(db: AsyncSession, value: str, *, exact: bool) -> ColumnElement[bool]:
    keywords = array_elements(db, Item.work["subjects"], objects=True)
    subject = keywords.c.value["subject"].as_string()
    predicate = subject == value if exact else subject.icontains(value, autoescape=True)
    return select(1).select_from(keywords).where(predicate).correlate(Item).exists()
