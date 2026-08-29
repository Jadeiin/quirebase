from __future__ import annotations

from typing import TYPE_CHECKING

from inquiro.richtext import convert_rich_text
from sqlalchemy import select

from quirebase.models import FileRevision, Item, ItemTag, Project, ProjectItem, Tag

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def search_text_for_item(db: Session, item: Item) -> str:
    full_text = db.scalar(
        select(FileRevision.full_text)
        .where(FileRevision.item_id == item.id, FileRevision.full_text.is_not(None))
        .order_by(FileRevision.created_at.desc())
        .limit(1)
    )
    tags = db.scalars(
        select(Tag.name).join(ItemTag, ItemTag.tag_id == Tag.id).where(ItemTag.item_id == item.id)
    ).all()
    projects = db.scalars(
        select(Project.name)
        .join(ProjectItem, ProjectItem.project_id == Project.id)
        .where(ProjectItem.item_id == item.id)
    ).all()
    return "\n".join(
        value
        for value in (
            convert_rich_text(item.title, source="html", target="text"),
            convert_rich_text(item.abstract, source="html", target="text"),
            item.authors,
            item.editors,
            item.keywords,
            item.custom_fields,
            item.identifiers,
            full_text,
            " ".join(tags),
            " ".join(projects),
        )
        if value
    )
