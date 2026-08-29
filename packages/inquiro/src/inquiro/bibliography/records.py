"""The neutral record vocabulary: Contributors and BibliographyRecords."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from bibtexparser.middlewares.names import parse_single_name_into_parts as _parse_single_name

from inquiro.richtext import convert_rich_text


def _corporate_family(value: str) -> str | None:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped.startswith("{") and stripped.endswith("}"):
        return stripped[1:-1].strip()
    return None


def _latex_decode(value: str) -> str:
    return convert_rich_text(value, source="latex", target="text")


@dataclass(frozen=True)
class Contributor:
    """A two-part contributor, with a nullable given name representing a literal name."""

    family_name: str
    given_name: str | None = None

    @classmethod
    def parse(cls, value: str) -> Contributor:
        parts = _parse_single_name(value)
        first = " ".join(parts.first).strip()
        if first in {"{}", "{ }"}:
            first = ""
        family = " ".join(parts.von + parts.last + parts.jr).strip() or value.strip()
        literal_family = _corporate_family(value)
        if literal_family is not None:
            return cls(family_name=_latex_decode(literal_family))
        return cls(
            family_name=_latex_decode(family),
            given_name=_latex_decode(first) or None,
        )

    @property
    def literal(self) -> bool:
        return self.given_name is None

    def display_name(self) -> str:
        return f"{self.family_name}, {self.given_name}" if self.given_name else self.family_name

    def storage_name(self) -> str:
        """Serialize a Contributor so a BibTeX name parser reads it back intact."""
        if self.literal:
            return f"{{{self.family_name}}}"
        return f"{self.family_name}, {self.given_name}"


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
    bibtex_type: str | None = None


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

    def mapping(value: str | None) -> tuple[tuple[str, str], ...]:
        try:
            parsed = json.loads(value or "{}")
        except (json.JSONDecodeError, TypeError):
            return ()
        if not isinstance(parsed, dict):
            return ()
        return tuple(
            (
                str(key),
                json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else str(val),
            )
            for key, val in parsed.items()
        )

    return BibliographyRecord(
        citation_key=getattr(item, "bibtex_id", None),
        reference_type=getattr(item, "reference_type", None) or "article",
        bibtex_type=getattr(item, "bibtex_type", None),
        title=getattr(item, "title", ""),
        authors=people(getattr(item, "authors", None)) if authors is None else authors,
        editors=people(getattr(item, "editors", None)) if editors is None else editors,
        abstract=getattr(item, "abstract", None),
        keywords=tuple(
            part.strip()
            for part in (getattr(item, "keywords", None) or "").split(";")
            if part.strip()
        ),
        publication_date=getattr(item, "publication_date", None),
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
        identifiers=mapping(getattr(item, "identifiers", None)),
        custom_fields=mapping(getattr(item, "custom_fields", None)),
    )
