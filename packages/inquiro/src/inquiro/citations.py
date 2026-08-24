from __future__ import annotations

import io
import re
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from inquiro.bibliography import first_url
from inquiro.parsing import normalize_reference_type

try:
    from citeproc import (
        Citation,
        CitationItem,
        CitationStylesBibliography,
        CitationStylesStyle,
        formatter,
    )
    from citeproc.source.json import CiteProcJSON
except ImportError:
    Citation = None
    CitationItem = None
    CitationStylesBibliography = None
    CitationStylesStyle = None
    formatter = None
    CiteProcJSON = None

try:
    from citeproc_styles import get_style_filepath, get_style_name
except ImportError:  # optional `citation` extra is not installed
    get_style_filepath = None
    get_style_name = None


@dataclass(frozen=True)
class CitationStyleOption:
    key: str
    name: str


@dataclass(frozen=True)
class CitationStyleSelection:
    matches: tuple[CitationStyleOption, ...]
    included: CitationStyleOption | None


class CitationEngineUnavailable(RuntimeError):
    """The optional CSL formatting engine is not installed."""


@dataclass(frozen=True)
class ExportOptions:
    include_abstract: bool = True
    preserve_case: bool = False
    abbreviate_journal: bool = False
    include_identifiers: bool = False
    include_custom_fields: bool = False


@lru_cache
def _builtin_style_catalog() -> tuple[CitationStyleOption, ...]:
    if get_style_filepath is None:
        return ()
    try:
        import importlib.resources

        roots = (
            importlib.resources.files("citeproc_styles") / "styles",
            importlib.resources.files("citeproc_styles") / "styles" / "dependent",
        )
        options: dict[str, CitationStyleOption] = {}
        for root in roots:
            for resource in root.iterdir():
                if resource.name.endswith(".csl"):
                    key = resource.name.removesuffix(".csl")
                    name = key
                    if get_style_name is not None:
                        with suppress(Exception):
                            name = get_style_name(key)
                    options[key] = CitationStyleOption(key=key, name=name)
        return tuple(sorted(options.values(), key=lambda option: option.name.casefold()))
    except Exception:
        return ()


def select_builtin_citation_styles(
    query: str = "", limit: int = 50, include: str = ""
) -> CitationStyleSelection:
    """Filter CSL styles and resolve an explicitly included style from one catalog snapshot."""
    catalog = _builtin_style_catalog()
    normalized_query = query.strip().casefold()
    matches = (
        option
        for option in catalog
        if not normalized_query
        or normalized_query in option.key.casefold()
        or normalized_query in option.name.casefold()
    )
    styles = tuple(list(matches)[: max(1, min(limit, 200))])
    normalized_include = include.strip().casefold()
    included = next(
        (
            option
            for option in catalog
            if normalized_include and option.key.casefold() == normalized_include
        ),
        None,
    )
    if included is not None and any(option.key == included.key for option in styles):
        included = None
    return CitationStyleSelection(matches=styles, included=included)


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

BIBLIOGRAPHY_MEDIA_TYPES: dict[str, str] = {
    "bibtex": "application/x-bibtex",
    "ris": "application/x-research-info-systems",
    "endnote": "application/x-endnote-refer",
}

BIBLIOGRAPHY_EXTENSIONS: dict[str, str] = {
    "bibtex": "bib",
    "ris": "ris",
    "endnote": "enw",
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


def parse_author_name(name_str: str) -> tuple[str, str | None]:
    cleaned = " ".join(name_str.split())
    if not cleaned:
        raise ValueError("author name cannot be empty")
    if "," in cleaned:
        parts = cleaned.split(",", 1)
        last = parts[0].strip()
        first = parts[1].strip() or None
        return last, first
    parts = cleaned.split()
    if len(parts) == 1:
        return parts[0], None
    return parts[-1], " ".join(parts[:-1])


def parse_author_list_string(raw: str | None) -> list[dict[str, str | None]]:
    if not raw or not raw.strip():
        return []
    authors: list[dict[str, str | None]] = []
    for part in raw.split(";"):
        cleaned = part.strip()
        if cleaned:
            last, first = parse_author_name(cleaned)
            authors.append({"last_name": last, "first_name": first})
    return authors


def _parse_names(value: str | None) -> list[dict[str, str | None]]:
    return [
        {
            "family": name["last_name"],
            **({"given": name["first_name"]} if name.get("first_name") else {}),
        }
        for name in parse_author_list_string(value)
    ]


def _parse_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [keyword.strip() for keyword in value.split(";") if keyword.strip()]


def item_to_csl_json(item: Any, options: ExportOptions | None = None) -> dict[str, Any]:
    options = options or ExportOptions()
    csl_type = REFERENCE_TYPE_TO_CSL.get(
        normalize_reference_type(getattr(item, "reference_type", None)) or "", "article"
    )
    record: dict[str, Any] = {
        "id": getattr(item, "id", "item-1"),
        "type": csl_type,
        "title": getattr(item, "title", ""),
    }
    optional: dict[str, Any] = {
        "abstract": item.abstract
        if options.include_abstract and hasattr(item, "abstract")
        else None,
        "DOI": getattr(item, "doi", None),
        "container-title": (
            item.journal_abbreviation
            if options.abbreviate_journal and getattr(item, "journal_abbreviation", None)
            else getattr(item, "publication_title", None)
        ),
        "container-title-short": getattr(item, "journal_abbreviation", None),
        "volume": getattr(item, "volume", None),
        "issue": getattr(item, "issue", None),
        "page": getattr(item, "pages", None),
        "publisher": getattr(item, "publisher", None),
        "publisher-place": getattr(item, "place_published", None),
        "URL": first_url(getattr(item, "urls", None)),
    }
    record.update({key: value for key, value in optional.items() if value})
    author = _parse_names(getattr(item, "authors", None))
    if author:
        record["author"] = author
    editor = _parse_names(getattr(item, "editors", None))
    if editor:
        record["editor"] = editor
    keyword = _parse_keywords(getattr(item, "keywords", None))
    if keyword:
        record["keyword"] = keyword
    issued = _date_parts(getattr(item, "publication_date", None))
    if issued:
        record["issued"] = {"date-parts": issued}
    return record


def _load_style(xml_text: str) -> Any:
    if CitationStylesStyle is None:
        raise CitationEngineUnavailable("CSL formatting requires the 'citation' extra")
    return CitationStylesStyle(io.BytesIO(xml_text.encode("utf-8")))


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
    item: Any,
    style_xml: str,
    output_format: str = "text",
    options: ExportOptions | None = None,
) -> str:
    """Render a single item to one formatted citation."""
    entries = render_bibliography(
        [item_to_csl_json(item, options=options)], style_xml, output_format
    )
    return entries[0] if entries else ""


def builtin_style_xml(style_key: str) -> str | None:
    """Return the CSL XML for a built-in style, or None if unavailable."""
    if get_style_filepath is None:
        return None
    try:
        path = get_style_filepath(style_key)
    except Exception:
        return None
    return Path(path).read_text(encoding="utf-8")


def is_valid_csl(xml_text: str) -> bool:
    """Return True when the text parses as a CSL style."""
    if not xml_text.strip():
        return False
    try:
        _load_style(xml_text)
    except Exception:
        return False
    return True
