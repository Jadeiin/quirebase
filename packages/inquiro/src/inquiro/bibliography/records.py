"""The neutral record vocabulary: Contributors and BibliographyRecords."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from inquiro.canonical import normalize_publication_date
from inquiro.names import ContributorName as Contributor


@dataclass(frozen=True)
class BibliographyRecord:
    citation_key: str | None
    reference_type: str
    title: str
    authors: tuple[Contributor, ...] = ()
    editors: tuple[Contributor, ...] = ()
    abstract: str | None = None
    keywords: tuple[str, ...] = ()
    publication_date: str | None = None
    publication_title: str | None = None
    journal_abbreviation: str | None = None
    book_title: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    location: str | None = None
    doi: str | None = None
    urls: tuple[str, ...] = ()
    identifiers: tuple[tuple[str, str], ...] = ()
    custom_fields: tuple[tuple[str, str], ...] = ()


def record_from_item(
    item: Any,
    *,
    authors: tuple[Contributor, ...] | None = None,
    editors: tuple[Contributor, ...] | None = None,
) -> BibliographyRecord:
    """Adapt any Item-shaped object onto a BibliographyRecord.

    Unknown or missing attributes default to empty values; explicit ``authors`` /
    ``editors`` tuples override the string parsing for link-resolved contributors.
    """

    def people(value: str | None) -> tuple[Contributor, ...]:
        return tuple(
            Contributor.parse(part.strip()) for part in (value or "").split(";") if part.strip()
        )

    def mapping(parsed: dict | None) -> tuple[tuple[str, str], ...]:
        if not isinstance(parsed, dict):
            return ()
        return tuple(
            (
                str(key),
                json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else str(val),
            )
            for key, val in parsed.items()
        )

    def serialized_mapping(value: str | None) -> tuple[tuple[str, str], ...]:
        try:
            return mapping(json.loads(value or "{}"))
        except (json.JSONDecodeError, TypeError):
            return ()

    return BibliographyRecord(
        citation_key=getattr(item, "citation_key", None),
        reference_type=getattr(item, "reference_type", None) or "document",
        title=getattr(item, "title", ""),
        authors=people(getattr(item, "authors", None)) if authors is None else authors,
        editors=people(getattr(item, "editors", None)) if editors is None else editors,
        abstract=getattr(item, "abstract", None),
        keywords=tuple(
            part.strip()
            for part in (getattr(item, "keywords", None) or "").split(";")
            if part.strip()
        ),
        publication_date=normalize_publication_date(getattr(item, "publication_date", None)),
        publication_title=getattr(item, "publication_title", None),
        journal_abbreviation=getattr(item, "journal_abbreviation", None),
        volume=getattr(item, "volume", None),
        issue=getattr(item, "issue", None),
        pages=getattr(item, "pages", None),
        publisher=getattr(item, "publisher", None),
        location=getattr(item, "place_published", None),
        doi=getattr(item, "doi", None),
        urls=tuple(
            part.strip()
            for part in (getattr(item, "urls", None) or "").splitlines()
            if part.strip()
        ),
        identifiers=serialized_mapping(getattr(item, "identifiers", None)),
        custom_fields=mapping(getattr(item, "custom_fields", None)),
    )
