"""CSL-JSON projection and rendering over the optional citeproc engine."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from inquiro.bibliography.records import BibliographyRecord, Contributor
from inquiro.bibliography.styles import (
    Citation,
    CitationEngineUnavailable,
    CitationItem,
    CitationStylesBibliography,
    CiteProcJSON,
    _load_style,
    formatter,
)
from inquiro.canonical import normalize_reference_type
from inquiro.richtext import convert_rich_text

REFERENCE_TYPE_TO_CSL: dict[str, str] = {
    "article": "article-journal",
    "book": "book",
    "chapter": "chapter",
    "preprint": "article",
    "conference": "paper-conference",
    "thesis": "thesis",
    "report": "report",
    "webpage": "webpage",
    "dataset": "dataset",
}

_DATE_PATTERN = re.compile(r"(\d{4})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?")


def _date_parts(value: str | None) -> list[list[int]] | None:
    if not value:
        return None
    match = _DATE_PATTERN.search(value.strip())
    if not match:
        return None
    year = int(match.group(1))
    if not 0 <= year <= 9999:
        return None
    month = int(match.group(2)) if match.group(2) else None
    day = int(match.group(3)) if match.group(3) else None
    if month and not 1 <= month <= 12:
        month = None
        day = None
    if day and not 1 <= day <= 31:
        day = None
    if day and month:
        return [[year, month, day]]
    if month:
        return [[year, month]]
    return [[year]]


def _names(contributors: tuple[Contributor, ...]) -> list[dict[str, str]]:
    people: list[dict[str, str]] = []
    for contributor in contributors:
        if contributor.literal:
            people.append({"literal": contributor.family_name})
        else:
            people.append({
                "family": contributor.family_name,
                "given": contributor.given_name or "",
            })
    return people


def record_to_csl_json(
    record: BibliographyRecord,
    options: Any | None = None,
    *,
    item_id: str | None = None,
) -> dict[str, Any]:
    include_abstract = getattr(options, "include_abstract", True) if options else True
    journal_mode = getattr(options, "journal_mode", "full") if options else "full"
    prefer_abbreviation = journal_mode in {"abbreviated", "prefer_abbreviated"}
    csl_type = REFERENCE_TYPE_TO_CSL.get(
        normalize_reference_type(record.reference_type) or "", "article"
    )
    entry: dict[str, Any] = {
        "id": item_id or record.citation_key or "item-1",
        "type": csl_type,
        "title": convert_rich_text(record.title, source="html", target="text"),
    }
    optional: dict[str, Any] = {
        "abstract": convert_rich_text(record.abstract, source="html", target="text")
        if include_abstract and record.abstract
        else None,
        "DOI": record.doi,
        "container-title": (
            record.journal_abbreviation
            if prefer_abbreviation and record.journal_abbreviation
            else record.publication_title
        ),
        "container-title-short": record.journal_abbreviation,
        "volume": record.volume,
        "issue": record.issue,
        "page": record.pages,
        "publisher": record.publisher,
        "publisher-place": record.location,
        "URL": record.urls[0] if record.urls else None,
    }
    entry.update({key: value for key, value in optional.items() if value})
    author = _names(record.authors)
    if author:
        entry["author"] = author
    editor = _names(record.editors)
    if editor:
        entry["editor"] = editor
    if record.keywords:
        entry["keyword"] = list(record.keywords)
    issued = _date_parts(record.publication_date)
    if issued:
        entry["issued"] = {"date-parts": issued}
    return entry


def render_bibliography(
    csl_json: list[dict[str, Any]], style_xml: str, output_format: str = "text"
) -> list[str]:
    """Render CSL-JSON records to styled bibliography entries."""
    if not csl_json:
        return []
    if (
        CiteProcJSON is None
        or CitationStylesBibliography is None
        or Citation is None
        or CitationItem is None
        or formatter is None
    ):
        raise CitationEngineUnavailable("CSL formatting requires the 'citation' extra")
    source = CiteProcJSON(csl_json)
    style = _load_style(style_xml)
    output = formatter.html if output_format == "html" else formatter.plain
    bibliography = CitationStylesBibliography(style, source, output)
    citation = Citation([CitationItem(record["id"]) for record in csl_json])
    bibliography.register(citation)
    if getattr(style.root, "bibliography", None) is not None:
        return ["".join(entry) for entry in bibliography.bibliography()]
    if getattr(style.root, "citation", None) is not None:
        return ["".join(bibliography.cite(citation, lambda _: None))]
    return [str(record.get("title", "")) for record in csl_json]


def render_citation(
    record: BibliographyRecord,
    style_xml: str,
    output_format: str = "text",
    options: Any | None = None,
) -> str:
    """Render a single record to one formatted citation."""
    entries = render_bibliography(
        [record_to_csl_json(record, options=options)], style_xml, output_format
    )
    return entries[0] if entries else ""
