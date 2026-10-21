"""SQLAlchemy expressions for querying the two supported JSON array dialects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Integer, Text, Uuid, case, cast, column, func, or_, select
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


def uuid_array_contains(db: AsyncSession, array: Any, value: Any) -> ColumnElement[bool]:
    """Match stored UUIDs without rebinding every JSON element as a SQL parameter."""
    elements = array_elements(db, array)
    if db.get_bind().dialect.name == "postgresql":
        return value.in_(select(cast(elements.c.value, Uuid)))
    # SQLite stores GUIDs as bytes; JSON receipts retain canonical hyphenated strings.
    return func.lower(func.hex(value)).in_(select(func.replace(elements.c.value, "-", "")))


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


_NAME_WHITESPACE = (
    " \t\n\r\v\f\x1c\x1d\x1e\x1f\x85\xa0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000"
)


def _visible_name(value: Any) -> Any:
    # Check display content without rewriting the Work's exact filter values.
    return func.coalesce(func.trim(value, _NAME_WHITESPACE), "")


def _joined_name(given: Any, family: Any) -> Any:
    first, last = _visible_name(given), _visible_name(family)
    return first + case(((first != "") & (last != ""), " "), else_="") + last


def _contributor_display_name(value: Any) -> Any:
    """SQL projection matching Inquiro's active-entity contributor_name display."""
    person = value["person"]
    provided = _visible_name(person["name"].as_string())
    return case(
        (
            value["type"].as_string() == "Person",
            case(
                (provided != "", provided),
                else_=_joined_name(
                    person["given_name"].as_string(), person["family_name"].as_string()
                ),
            ),
        ),
        else_=_visible_name(value["organization"]["name"].as_string()),
    )


def _grouped_contributor_name(family: Any, given: Any, display: Any) -> Any:
    """Use a supplied name only when it describes the entire exact-name bucket."""
    visible = func.nullif(display, "")
    first = func.min(visible)
    return case((first == func.max(visible), first), else_=_joined_name(given, family))


def author_role(db: AsyncSession, value: Any) -> ColumnElement[bool]:
    roles = array_elements(db, value["roles"])
    return select(1).select_from(roles).where(roles.c.value == "Author").exists()


def first_contributor_sort_name(db: AsyncSession) -> ColumnElement[str]:
    """First named Author's surname (or literal name), falling back to the first Editor."""
    if db.get_bind().dialect.name == "postgresql":
        contributors = (
            func
            .jsonb_array_elements(Item.work["contributors"])
            .table_valued(column("value", JSONB), with_ordinality="position")
            .render_derived()
            .lateral()
        )
        position = contributors.c.position
    else:
        contributors = func.json_each(Item.work["contributors"]).table_valued(
            column("value", JSON), column("key", Integer)
        )
        position = contributors.c.key
    family, _ = contributor_name_parts(contributors.c.value)
    is_author = author_role(db, contributors.c.value)
    roles = array_elements(db, contributors.c.value["roles"])
    is_editor = select(1).select_from(roles).where(roles.c.value == "Editor").exists()
    return (
        select(family)
        .select_from(contributors)
        .where(or_(is_author, is_editor), func.trim(family) != "")
        .order_by(case((is_author, 0), else_=1), position)
        .limit(1)
        .correlate(Item)
        .scalar_subquery()
    )


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
