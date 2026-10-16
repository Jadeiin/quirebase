from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from advanced_alchemy.filters import LimitOffset
from inquiro.richtext import convert_rich_text
from inquiro.work import work_identifiers
from sqlalchemy import Select, or_, select

from quirebase.access import (
    ResourceAction,
    require_project_context,
    require_workspace_action,
    workspace_items_query,
)
from quirebase.access.scope import workspace_select
from quirebase.core.errors import ValidationFailure
from quirebase.core.persistence import select_page
from quirebase.models import (
    Attachment,
    FileRevision,
    Item,
    ItemRead,
    ItemTag,
    LoginSession,
    ProjectItem,
    Tag,
    User,
)
from quirebase.projects import list_workspace_projects
from quirebase.search import search_index

from ._json_queries import author_condition, keyword_condition

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement


@dataclass(frozen=True)
class LibraryFilter:
    q: str = ""
    tag: str = ""
    project: UUID | None = None
    year: str = ""
    keyword: str = ""
    author: str = ""
    has_files: bool | None = None
    reference_type: str | None = None
    keyword_exact: str | None = None
    author_last_name: str | None = None
    author_first_name: str | None = None
    publication_title: str | None = None


async def _library_query(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    filters: LibraryFilter,
) -> Select[tuple[Item]]:
    """Resolve visibility once for search, suggestions and metadata facets."""
    context = await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    item_query = workspace_items_query(context)
    matching_ids = (
        await search_index(db).matching_item_ids(db, filters.q) if filters.q.strip() else None
    )
    if matching_ids is not None:
        item_query = item_query.where(Item.id.in_(matching_ids))
    if filters.tag:
        tag_filter: ColumnElement[bool]
        try:
            tag_id = UUID(filters.tag)
        except ValueError:
            tag_filter = Tag.name == filters.tag
        else:
            tag_filter = or_(Tag.id == tag_id, Tag.name == filters.tag)
        item_query = item_query.where(
            Item.id.in_(
                workspace_select(ItemTag, context)
                .with_only_columns(ItemTag.item_id)
                .join(Tag, Tag.id == ItemTag.tag_id)
                .where(
                    tag_filter,
                )
            )
        )
    if filters.project:
        await require_project_context(
            db, user, workspace_id, filters.project, ResourceAction.workspace_read
        )
        item_query = item_query.where(
            Item.id.in_(
                workspace_select(ProjectItem, context)
                .with_only_columns(ProjectItem.item_id)
                .where(ProjectItem.project_id == filters.project)
            )
        )
    if filters.year:
        item_query = item_query.where(
            Item.work["date_published"].as_string().startswith(filters.year, autoescape=True)
        )
    if filters.reference_type is not None:
        item_query = item_query.where(Item.work["type"].as_string() == filters.reference_type)
    if filters.publication_title is not None:
        item_query = item_query.where(
            Item.work["container"]["title"].as_string() == filters.publication_title
        )
    if filters.keyword.strip():
        item_query = item_query.where(keyword_condition(db, filters.keyword.strip(), exact=False))
    if filters.keyword_exact is not None:
        item_query = item_query.where(keyword_condition(db, filters.keyword_exact, exact=True))
    if filters.author_first_name is not None and filters.author_last_name is None:
        raise ValidationFailure("an exact author filter requires a last name")
    if filters.author.strip() or filters.author_last_name is not None:
        item_query = item_query.where(
            author_condition(
                db,
                text=filters.author.strip(),
                last_name=filters.author_last_name,
                first_name=filters.author_first_name,
            )
        )
    if filters.has_files is not None:
        file_conditions = [
            select(model.id)
            .where(model.item_id == Item.id, model.workspace_id == workspace_id)
            .exists()
            for model in (FileRevision, Attachment)
        ]
        file_condition = or_(*file_conditions)
        item_query = item_query.where(file_condition if filters.has_files else ~file_condition)
    return item_query


async def search_library(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    q: str = "",
    tag: str = "",
    project: UUID | None = None,
    year: str = "",
    keyword: str = "",
    author: str = "",
    limit: int = 25,
    offset: int = 0,
    sort: Literal["updated", "created", "title"] = "updated",
    has_files: bool | None = None,
    reference_type: str | None = None,
    keyword_exact: str | None = None,
    author_last_name: str | None = None,
    author_first_name: str | None = None,
    publication_title: str | None = None,
) -> tuple[list[Item], int]:
    item_query = await _library_query(
        db,
        user,
        workspace_id,
        LibraryFilter(
            q=q,
            tag=tag,
            project=project,
            year=year,
            keyword=keyword,
            author=author,
            has_files=has_files,
            reference_type=reference_type,
            keyword_exact=keyword_exact,
            author_last_name=author_last_name,
            author_first_name=author_first_name,
            publication_title=publication_title,
        ),
    )
    expression = {
        "updated": Item.updated_at,
        "created": Item.created_at,
        "title": Item.work["title"].as_string(),
    }[sort]
    records, total = await select_page(
        db,
        item_query.order_by(expression.asc() if sort == "title" else expression.desc(), Item.id),
        Item,
        LimitOffset(limit=limit, offset=offset),
    )
    return list(records), total


def _normalized_title(title: str) -> str:
    return re.sub(
        r"[^\w]+",
        " ",
        convert_rich_text(title, source="html", target="text").casefold(),
    ).strip()


async def get_dashboard_data(db: AsyncSession, user: User, workspace_id: UUID) -> dict[str, Any]:
    context = await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    new_items = list(
        (
            await db.scalars(
                workspace_items_query(context).order_by(Item.created_at.desc()).limit(10)
            )
        ).all()
    )
    recent_items = list(
        (
            await db.execute(
                workspace_items_query(context)
                .join(ItemRead, ItemRead.item_id == Item.id)
                .where(
                    ItemRead.user_id == user.id,
                )
                .with_only_columns(Item, ItemRead.last_read_at)
                .order_by(ItemRead.last_read_at.desc())
                .limit(10)
            )
        ).all()
    )
    project_rows, project_count = await list_workspace_projects(db, context, view="mine", limit=10)
    projects = [project for project, _, _ in project_rows]
    sessions = list(
        (
            await db.scalars(
                select(LoginSession)
                .where(LoginSession.user_id == user.id)
                .order_by(LoginSession.created_at.desc())
                .limit(10)
            )
        ).all()
    )
    return {
        "new_items": new_items,
        "recent_items": recent_items,
        "projects": projects,
        "project_count": project_count,
        "sessions": sessions,
    }


async def find_duplicates(
    db: AsyncSession, user: User, workspace_id: UUID, mode: str
) -> list[list[Item]]:
    if mode not in ("", "identifier", "title", "similar"):
        raise ValidationFailure(f"unknown duplicate mode: {mode}")
    if not mode:
        return []
    context = await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    limit = 500 if mode == "similar" else 2000
    items = list(
        (
            await db.scalars(
                workspace_items_query(context).order_by(Item.work["title"].as_string()).limit(limit)
            )
        ).all()
    )
    groups: list[list[Item]] = []
    buckets: dict[str, list[Item]] = {}
    if mode == "identifier":
        # Connected suggestions handle A↔B↔C overlaps without arbitrarily
        # selecting one identifier or treating a match as a merge command.
        parents = {item.id: item.id for item in items}

        def root(item_id):
            while parents[item_id] != item_id:
                parents[item_id] = parents[parents[item_id]]
                item_id = parents[item_id]
            return item_id

        owners: dict[tuple[str, str], UUID] = {}
        for item in items:
            for pair in work_identifiers(item.work):
                if pair in owners:
                    parents[root(item.id)] = root(owners[pair])
                else:
                    owners[pair] = item.id
        for item in items:
            buckets.setdefault(root(item.id), []).append(item)
    elif mode == "title":
        for item in items:
            buckets.setdefault(_normalized_title(item.work.get("title", "")), []).append(item)
    elif mode == "similar":
        remaining = items.copy()
        while remaining:
            anchor = remaining.pop(0)
            key = _normalized_title(anchor.work.get("title", ""))
            matches = [anchor]
            for candidate in remaining.copy():
                if (
                    SequenceMatcher(
                        None, key, _normalized_title(candidate.work.get("title", ""))
                    ).ratio()
                    >= 0.9
                ):
                    matches.append(candidate)
                    remaining.remove(candidate)
            if len(matches) > 1:
                groups.append(matches)
        return groups
    return [group for group in buckets.values() if len({row.id for row in group}) > 1]
