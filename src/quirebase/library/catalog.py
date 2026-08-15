from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from quirebase.access.items import visible_items_query
from quirebase.access.projects import visible_projects
from quirebase.core.errors import ValidationFailure
from quirebase.models import (
    FileRevision,
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
    from sqlalchemy.orm import Session


def search_library(
    db: Session,
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
    matching_ids = search_index(db).search(db, q) if q.strip() else None
    if matching_ids is not None:
        item_query = item_query.where(Item.id.in_(matching_ids))
    if tag:
        item_query = item_query.where(
            Item.id.in_(select(ItemTag.item_id).where(ItemTag.tag_id == tag))
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
    total = db.scalar(select(func.count()).select_from(item_query.subquery())) or 0
    items = list(
        db.scalars(
            item_query
            .order_by(Item.updated_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        ).all()
    )
    accessible_ids = visible_items_query(user).with_only_columns(Item.id).subquery()
    tags = list(
        db.scalars(
            select(Tag)
            .join(ItemTag, ItemTag.tag_id == Tag.id)
            .where(ItemTag.item_id.in_(select(accessible_ids.c.id)))
            .distinct()
            .order_by(Tag.name)
        ).all()
    )
    dates = db.scalars(
        visible_items_query(user)
        .with_only_columns(Item.publication_date)
        .where(Item.publication_date.is_not(None))
    ).all()
    years = sorted({value[:4] for value in dates if value and value[:4].isdigit()}, reverse=True)
    return items, total, tags, years


def get_dashboard_data(db: Session, user: User) -> dict[str, Any]:
    new_items = list(
        db.scalars(visible_items_query(user).order_by(Item.created_at.desc()).limit(10)).all()
    )
    recent_items = list(
        db.execute(
            visible_items_query(user)
            .join(ItemRead, ItemRead.item_id == Item.id)
            .where(ItemRead.user_id == user.id)
            .with_only_columns(Item, ItemRead.last_read_at)
            .order_by(ItemRead.last_read_at.desc())
            .limit(10)
        ).all()
    )
    projects = visible_projects(db, user)
    sessions = list(
        db.scalars(
            select(LoginSession)
            .where(LoginSession.user_id == user.id)
            .order_by(LoginSession.created_at.desc())
            .limit(10)
        ).all()
    )
    return {
        "new_items": new_items,
        "recent_items": recent_items,
        "projects": projects,
        "sessions": sessions,
    }


def find_duplicates(db: Session, user: User, mode: str) -> list[list[Item]]:
    if mode not in ("", "doi", "pdf", "title", "similar"):
        raise ValidationFailure(f"unknown duplicate mode: {mode}")
    if not mode:
        return []
    limit = 500 if mode == "similar" else 2000
    items = list(db.scalars(visible_items_query(user).order_by(Item.title).limit(limit)).all())
    groups: list[list[Item]] = []
    buckets: dict[str, list[Item]] = {}
    if mode == "doi":
        for item in items:
            key = (item.doi or "").strip().lower()
            if key:
                buckets.setdefault(key, []).append(item)
    elif mode == "pdf":
        revisions = db.execute(
            select(FileRevision.item_id, FileRevision.sha256).where(
                FileRevision.item_id.in_([item.id for item in items])
            )
        ).all()
        item_map = {item.id: item for item in items}
        for item_id, digest in revisions:
            group = buckets.setdefault(digest, [])
            if all(item.id != item_id for item in group):
                group.append(item_map[item_id])
    elif mode == "title":
        normalize = lambda title: re.sub(r"[^\w]+", " ", title.casefold()).strip()
        for item in items:
            buckets.setdefault(normalize(item.title), []).append(item)
    elif mode == "similar":
        normalize = lambda title: re.sub(r"[^\w]+", " ", title.casefold()).strip()
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
