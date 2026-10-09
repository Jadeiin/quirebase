from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from advanced_alchemy.filters import (
    ExistsFilter,
    FilterGroup,
    LimitOffset,
    NotExistsFilter,
    OrderBy,
    SearchFilter,
)
from inquiro.richtext import convert_rich_text
from sqlalchemy import or_, select

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

if TYPE_CHECKING:
    from advanced_alchemy.filters import StatementFilter
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement


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
) -> tuple[list[Item], int]:
    context = await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    item_query = workspace_items_query(context)
    matching_ids = await search_index(db).matching_item_ids(db, q) if q.strip() else None
    if matching_ids is not None:
        item_query = item_query.where(Item.id.in_(matching_ids))
    if tag:
        tag_filter: ColumnElement[bool]
        try:
            tag_id = UUID(tag)
        except ValueError:
            tag_filter = Tag.name == tag
        else:
            tag_filter = or_(Tag.id == tag_id, Tag.name == tag)
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
    if project:
        await require_project_context(
            db, user, workspace_id, project, ResourceAction.workspace_read
        )
        item_query = item_query.where(
            Item.id.in_(
                workspace_select(ProjectItem, context)
                .with_only_columns(ProjectItem.item_id)
                .where(ProjectItem.project_id == project)
            )
        )
    if year:
        item_query = item_query.where(Item.publication_date.startswith(year))
    filters: list[StatementFilter] = [LimitOffset(limit=limit, offset=offset)]
    for field, value in (("keywords", keyword), ("authors", author)):
        if value.strip():
            filters.append(SearchFilter(field_name=field, value=value.strip(), ignore_case=True))
    if has_files is not None:
        exists_type = ExistsFilter if has_files else NotExistsFilter
        file_filters: list[StatementFilter] = [
            exists_type(values=[model.item_id == Item.id, model.workspace_id == workspace_id])
            for model in (FileRevision, Attachment)
        ]
        if has_files:
            filters.append(FilterGroup(logical_operator=or_, filters=file_filters))
        else:
            filters.extend(file_filters)
    sort_field = {"updated": "updated_at", "created": "created_at", "title": "title"}[sort]
    filters.extend([
        OrderBy(field_name=sort_field, sort_order="asc" if sort == "title" else "desc"),
        OrderBy(field_name="id"),
    ])
    records, total = await select_page(db, item_query, Item, *filters)
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
    if mode not in ("", "doi", "title", "similar"):
        raise ValidationFailure(f"unknown duplicate mode: {mode}")
    if not mode:
        return []
    context = await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    limit = 500 if mode == "similar" else 2000
    items = list(
        (await db.scalars(workspace_items_query(context).order_by(Item.title).limit(limit))).all()
    )
    groups: list[list[Item]] = []
    buckets: dict[str, list[Item]] = {}
    if mode == "doi":
        for item in items:
            key = (item.doi or "").strip().lower()
            if key:
                buckets.setdefault(key, []).append(item)
    elif mode == "title":
        for item in items:
            buckets.setdefault(_normalized_title(item.title), []).append(item)
    elif mode == "similar":
        remaining = items.copy()
        while remaining:
            anchor = remaining.pop(0)
            key = _normalized_title(anchor.title)
            matches = [anchor]
            for candidate in remaining.copy():
                if SequenceMatcher(None, key, _normalized_title(candidate.title)).ratio() >= 0.9:
                    matches.append(candidate)
                    remaining.remove(candidate)
            if len(matches) > 1:
                groups.append(matches)
        return groups
    return [group for group in buckets.values() if len({row.id for row in group}) > 1]
