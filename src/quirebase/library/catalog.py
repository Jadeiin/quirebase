from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from inquiro.richtext import convert_rich_text
from sqlalchemy import func, or_, select

from quirebase.access.items import visible_items_query
from quirebase.access.projects import visible_projects
from quirebase.core.errors import ValidationFailure
from quirebase.models import (
    Item,
    ItemRead,
    ItemTag,
    LoginSession,
    ProjectItem,
    Tag,
    User,
)
from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def search_library(
    db: AsyncSession,
    user: User,
    q: str = "",
    tag: str = "",
    project: str = "",
    year: str = "",
    keyword: str = "",
    author: str = "",
    page: int = 1,
    per_page: int = 25,
) -> tuple[list[Item], int, list[Tag], list[str]]:
    page = max(page, 1)
    item_query = visible_items_query(user)
    matching_ids = await search_index(db).search(db, q) if q.strip() else None
    if matching_ids is not None:
        item_query = item_query.where(Item.id.in_(matching_ids))
    if tag:
        item_query = item_query.where(
            Item.id.in_(
                select(ItemTag.item_id)
                .join(Tag, Tag.id == ItemTag.tag_id)
                .where(or_(Tag.id == tag, Tag.name == tag))
            )
        )
    if project:
        item_query = item_query.where(
            Item.id.in_(select(ProjectItem.item_id).where(ProjectItem.project_id == project))
        )
    if year:
        item_query = item_query.where(Item.publication_date.startswith(year))
    if keyword:
        item_query = item_query.where(Item.keywords.ilike(f"%{keyword}%"))
    if author:
        item_query = item_query.where(Item.authors.ilike(f"%{author}%"))
    total = await db.scalar(select(func.count()).select_from(item_query.subquery())) or 0
    items = list(
        (
            await db.scalars(
                item_query
                .order_by(Item.updated_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
    )
    accessible_ids = visible_items_query(user).with_only_columns(Item.id).subquery()
    tags = list(
        (
            await db.scalars(
                select(Tag)
                .join(ItemTag, ItemTag.tag_id == Tag.id)
                .where(ItemTag.item_id.in_(select(accessible_ids.c.id)))
                .distinct()
                .order_by(Tag.name)
            )
        ).all()
    )
    dates = (
        await db.scalars(
            visible_items_query(user)
            .with_only_columns(Item.publication_date)
            .where(Item.publication_date.is_not(None))
        )
    ).all()
    years = sorted({value[:4] for value in dates if value and value[:4].isdigit()}, reverse=True)
    return items, total, tags, years


async def get_dashboard_data(db: AsyncSession, user: User) -> dict[str, Any]:
    new_items = list(
        (
            await db.scalars(visible_items_query(user).order_by(Item.created_at.desc()).limit(10))
        ).all()
    )
    recent_items = list(
        (
            await db.execute(
                visible_items_query(user)
                .join(ItemRead, ItemRead.item_id == Item.id)
                .where(ItemRead.user_id == user.id)
                .with_only_columns(Item, ItemRead.last_read_at)
                .order_by(ItemRead.last_read_at.desc())
                .limit(10)
            )
        ).all()
    )
    projects = await visible_projects(db, user)
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
        "sessions": sessions,
    }


async def find_duplicates(db: AsyncSession, user: User, mode: str) -> list[list[Item]]:
    if mode not in ("", "doi", "title", "similar"):
        raise ValidationFailure(f"unknown duplicate mode: {mode}")
    if not mode:
        return []
    limit = 500 if mode == "similar" else 2000
    items = list(
        (await db.scalars(visible_items_query(user).order_by(Item.title).limit(limit))).all()
    )
    groups: list[list[Item]] = []
    buckets: dict[str, list[Item]] = {}
    if mode == "doi":
        for item in items:
            key = (item.doi or "").strip().lower()
            if key:
                buckets.setdefault(key, []).append(item)
    elif mode == "title":
        normalize = lambda title: re.sub(
            r"[^\w]+",
            " ",
            convert_rich_text(title, source="html", target="text").casefold(),
        ).strip()
        for item in items:
            buckets.setdefault(normalize(item.title), []).append(item)
    elif mode == "similar":
        normalize = lambda title: re.sub(
            r"[^\w]+",
            " ",
            convert_rich_text(title, source="html", target="text").casefold(),
        ).strip()
        remaining = items.copy()
        while remaining:
            anchor = remaining.pop(0)
            key = normalize(anchor.title)
            matches = [anchor]
            for candidate in remaining.copy():
                if SequenceMatcher(None, key, normalize(candidate.title)).ratio() >= 0.9:
                    matches.append(candidate)
                    remaining.remove(candidate)
            if len(matches) > 1:
                groups.append(matches)
        return groups
    return [group for group in buckets.values() if len({row.id for row in group}) > 1]
