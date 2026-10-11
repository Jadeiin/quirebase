from __future__ import annotations

import json
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
            "\n".join(
                " ".join(
                    part
                    for part in (
                        row["display_name"],
                        row.get("family_name"),
                        row.get("given_name"),
                        row.get("suffix"),
                    )
                    if part
                )
                for row in (*item.authors, *item.editors)
            ),
            "\n".join(item.keywords),
            json.dumps(item.custom_fields, ensure_ascii=False) if item.custom_fields else None,
            "\n".join(row.value for row in item.identifier_links),
        )
        if value
    )


def search_text_for_revision(revision: FileRevision) -> str:
    """Return extracted PDF text for the revision-owned projection."""

    return revision.full_text or ""
