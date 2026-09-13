from __future__ import annotations

from typing import TYPE_CHECKING

from inquiro.richtext import convert_rich_text

if TYPE_CHECKING:
    from quirebase.models import FileRevision, Item


def search_text_for_item(item: Item) -> str:
    """Return only bibliographic metadata for the Item projection."""
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
        )
        if value
    )


def search_text_for_revision(revision: FileRevision) -> str:
    """Return extracted PDF text for the revision-owned projection."""

    return revision.full_text or ""
