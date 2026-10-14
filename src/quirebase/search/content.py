from __future__ import annotations

import re
from typing import TYPE_CHECKING

from inquiro.richtext import convert_rich_text
from inquiro.work import contributor_name, work_identifiers

if TYPE_CHECKING:
    from quirebase.models import FileRevision, Item


def _contributor_search_text(credit: dict) -> str:
    entity = credit.get(credit["type"].lower(), {})
    return "\n".join(
        dict.fromkeys(
            value
            for value in (
                contributor_name(credit),
                entity.get("family_name"),
                entity.get("given_name"),
            )
            if value
        )
    )


def search_text_for_item(item: Item) -> str:
    """Return only bibliographic metadata for the Item projection."""
    work = item.work
    identifiers = list(
        dict.fromkeys([
            work.get("id", ""),
            *[row["identifier"] for row in work.get("identifiers", [])],
            *[value for _, value in sorted(work_identifiers(work))],
        ])
    )
    return "\n".join(
        value
        for value in (
            convert_rich_text(work.get("title"), source="html", target="text"),
            convert_rich_text(work.get("description"), source="html", target="text"),
            "\n".join(row["description"] for row in work.get("additional_descriptions", [])),
            "\n".join(
                _contributor_search_text(row)
                for row in work.get("contributors", [])
                if set(row.get("roles", [])) & {"Author", "Editor"}
            ),
            "\n".join(row["subject"] for row in work.get("subjects", [])),
            "\n".join(identifiers),
            "\n".join(re.sub(r"[^\w]+", " ", value) for value in identifiers),
        )
        if value
    )


def search_text_for_revision(revision: FileRevision) -> str:
    """Return extracted PDF text for the revision-owned projection."""

    return revision.full_text or ""
