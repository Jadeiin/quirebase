"""Canonical text helpers shared by Provider payload parsing and the host application."""

from __future__ import annotations

from typing import Any

from inquiro.richtext import convert_rich_text

__all__ = [
    "CANONICAL_REFERENCE_TYPE_MAP",
    "clean_markup",
    "clean_rich_markup",
    "collect_urls",
    "first_text",
    "normalize_reference_type",
]


def first_text(value: Any) -> str | None:
    """Collapse a scalar or first list element into single-spaced text."""
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def clean_markup(value: str | None) -> str | None:
    """Strip markup from provider text and collapse whitespace; None for empty results."""
    if not value:
        return None
    return first_text(convert_rich_text(value, source="html", target="text"))


def clean_rich_markup(value: str | None) -> str | None:
    """Canonicalize provider text to balanced rich-text HTML; None when it renders empty."""
    if not value:
        return None
    canonical = first_text(convert_rich_text(value, source="html", target="html"))
    if not canonical or not convert_rich_text(canonical, source="html", target="text"):
        return None
    return canonical


def collect_urls(*candidates: Any) -> str | None:
    urls: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in urls:
            urls.append(candidate)
    return "\n".join(urls) if urls else None


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
    "incollection": "chapter",
    "conference": "conference",
    "conference-paper": "conference",
    "inproceedings": "conference",
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
    "online": "webpage",
    "webpage": "webpage",
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
