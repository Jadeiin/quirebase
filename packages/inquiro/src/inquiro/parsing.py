from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from inquiro.models import SearchClause

HTML_TAG = re.compile(r"<[^>]+>")


def _collect_urls(*candidates: Any) -> str | None:
    urls: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in urls:
            urls.append(candidate)
    return "\n".join(urls) if urls else None


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def _clean_markup(value: str | None) -> str | None:
    if not value:
        return None
    return _first(html.unescape(HTML_TAG.sub(" ", value)))


def _date_parts(message: dict) -> str | None:
    parts = (
        message.get("published-print")
        or message.get("published-online")
        or message.get("issued")
        or {}
    ).get("date-parts", [])
    if not parts:
        return None
    return "-".join(
        str(number).zfill(2) if index else str(number) for index, number in enumerate(parts[0])
    )


def reconstruct_openalex_abstract(inverted_index: Any) -> str | None:
    if not isinstance(inverted_index, dict) or not inverted_index:
        return None
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        if isinstance(positions, list):
            word_positions.extend((pos, word) for pos in positions if isinstance(pos, int))
    if not word_positions:
        return None
    word_positions.sort(key=lambda item: item[0])
    return _clean_markup(" ".join(word for _, word in word_positions))


def _collect_openalex_keyword_names(*collections: Any) -> list[str]:
    names: list[str] = []
    for entries in collections:
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = _clean_markup(_first(entry.get("display_name")))
            if name and name not in names:
                names.append(name)
    return names


# Keyed on dash-form lower-case aliases only; normalize_reference_type replaces
# "_" and spaces with "-" before lookup, so variant forms need no entries here.
CANONICAL_REFERENCE_TYPE_MAP: dict[str, str] = {
    "article": "article",
    "journal-article": "article",
    "article-journal": "article",
    "jour": "article",
    "book": "book",
    "monograph": "book",
    "edited-book": "book",
    "chapter": "chapter",
    "book-chapter": "chapter",
    "book-section": "chapter",
    "conference": "conference",
    "conference-paper": "conference",
    "proceedings-article": "conference",
    "proceedings": "conference",
    "paper-conference": "conference",
    "preprint": "preprint",
    "posted-content": "preprint",
    "working-paper": "preprint",
    "thesis": "thesis",
    "dissertation": "thesis",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "report": "report",
    "techreport": "report",
    "dataset": "dataset",
    "patent": "patent",
    "standard": "standard",
    "generic": "generic",
    "misc": "generic",
    "other": "generic",
    "unpublished": "generic",
}


def normalize_reference_type(value: Any) -> str | None:
    if not value:
        return None
    val_str = str(value).strip().lower()
    cleaned = val_str.replace("_", "-").replace(" ", "-")
    return CANONICAL_REFERENCE_TYPE_MAP.get(cleaned, cleaned)


def _boolean_query(
    clauses: list[SearchClause], fields: dict[str, str], *, field_prefix: bool = False
) -> str:
    parts: list[str] = []
    for index, clause in enumerate(clauses):
        value = clause.term.replace('"', " ").replace("\\", " ").strip()
        field = fields.get(clause.field, fields["any"])
        tagged = f'{field}"{value}"' if field_prefix else f'"{value}"{field}'
        if clause.operator == "not":
            parts.append(f"NOT {tagged}")
        elif index and clause.operator == "or":
            parts.append(f"OR {tagged}")
        else:
            parts.append(("AND " if index else "") + tagged)
    return " ".join(parts)
