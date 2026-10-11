"""SQLAlchemy expressions for querying the two supported JSON array dialects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Text, case, column, func, or_, select, type_coerce
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


def contributor_name_parts(value: Any) -> tuple[Any, Any, Any]:
    """Project source name facts onto the record-local name query dimension."""
    organization = value["kind"].as_string() == "organization"
    family = case(
        (organization, value["display_name"].as_string()),
        else_=func.coalesce(value["family_name"].as_string(), value["display_name"].as_string()),
    )
    given = case((organization, None), else_=value["given_name"].as_string())
    suffix = case((organization, None), else_=value["suffix"].as_string())
    return family, given, suffix


def author_condition(
    db: AsyncSession,
    *,
    text: str = "",
    last_name: str | None = None,
    first_name: str | None = None,
    suffix: str | None = None,
) -> ColumnElement[bool]:
    if last_name is not None:
        name: dict[str, str | None] = {"family_name": " ".join(last_name.split())}
        if first_name is not None:
            name["given_name"] = " ".join(first_name.split()) or None
        if suffix is not None and (normalized_suffix := " ".join(suffix.split())):
            name["suffix"] = normalized_suffix
    authors = array_elements(db, Item.authors, objects=True)
    family, given, name_suffix = contributor_name_parts(authors.c.value)
    display = authors.c.value["display_name"].as_string()
    query = select(1).select_from(authors)
    if last_name is not None:
        query = query.where(family == name["family_name"])
        if first_name is not None:
            query = query.where(
                given == name["given_name"] if name["given_name"] is not None else given.is_(None)
            )
        if suffix is not None:
            query = query.where(func.coalesce(name_suffix, "") == " ".join(suffix.split()))
    if text:
        full_name = family + func.coalesce(" " + name_suffix, "") + ", " + func.coalesce(given, "")
        query = query.where(
            or_(
                display.icontains(text, autoescape=True),
                name_suffix.icontains(text, autoescape=True),
                family.icontains(text, autoescape=True),
                given.icontains(text, autoescape=True),
                full_name.icontains(text, autoescape=True),
            )
        )
    predicate: ColumnElement[bool] = query.correlate(Item).exists()
    if last_name is not None and db.get_bind().dialect.name == "postgresql":
        # The containment prefilter can use GIN. EXISTS also handles literal
        # names and absent optional fields without conflating distinct names.
        name_parts = {key: value for key, value in name.items() if value is not None}
        display_parts = {
            "display_name": name_parts["family_name"],
            **{key: value for key, value in name_parts.items() if key != "family_name"},
        }
        predicate = predicate & or_(
            type_coerce(Item.authors, JSONB).contains([name_parts]),
            type_coerce(Item.authors, JSONB).contains([display_parts]),
        )
    return predicate


def keyword_condition(db: AsyncSession, value: str, *, exact: bool) -> ColumnElement[bool]:
    if exact and db.get_bind().dialect.name == "postgresql":
        return type_coerce(Item.keywords, JSONB).contains([value])
    keywords = array_elements(db, Item.keywords)
    predicate = (
        keywords.c.value == value if exact else keywords.c.value.icontains(value, autoescape=True)
    )
    return select(1).select_from(keywords).where(predicate).correlate(Item).exists()
