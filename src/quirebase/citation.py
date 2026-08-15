from __future__ import annotations

import io
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from citeproc import (
    Citation,
    CitationItem,
    CitationStylesBibliography,
    CitationStylesStyle,
    formatter,
)
from citeproc.source.json import CiteProcJSON

try:
    from citeproc_styles import get_style_filepath
except ImportError:  # optional `citation` extra is not installed
    get_style_filepath = None

if TYPE_CHECKING:
    from .models import Item

BUILTIN_STYLES: dict[str, str] = {
    "apa": "APA 7th edition",
    "chicago-author-date": "Chicago (author-date)",
    "modern-language-association": "MLA",
    "harvard-cite-them-right": "Harvard",
    "american-medical-association": "Vancouver / AMA",
    "ieee": "IEEE",
}

REFERENCE_TYPE_TO_CSL: dict[str, str] = {
    "article": "article-journal",
    "journal-article": "article-journal",
    "journal_article": "article-journal",
    "book": "book",
    "chapter": "chapter",
    "book-chapter": "chapter",
    "preprint": "article",
    "conference": "paper-conference",
    "conference-paper": "paper-conference",
    "proceedings": "paper-conference",
    "thesis": "thesis",
    "dissertation": "thesis",
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


def _parse_name(name: str) -> dict[str, str]:
    name = name.strip()
    if not name:
        return {}
    if "," in name:
        family, _, given = name.partition(",")
        family = family.strip()
        given = given.strip()
        return {"family": family, "given": given} if given else {"family": family}
    parts = name.split()
    if len(parts) == 1:
        return {"family": parts[0]}
    return {"family": parts[-1], "given": " ".join(parts[:-1])}


def _parse_names(value: str | None) -> list[dict[str, str]]:
    if not value:
        return []
    names = [name for name in value.split(";") if name.strip()]
    return [_parse_name(name) for name in names if _parse_name(name)]


def _parse_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [keyword.strip() for keyword in value.split(";") if keyword.strip()]


def item_to_csl_json(item: Item) -> dict[str, Any]:
    reference_type = (item.reference_type or "").lower()
    csl_type = REFERENCE_TYPE_TO_CSL.get(reference_type, "article")
    record: dict[str, Any] = {
        "id": item.id,
        "type": csl_type,
        "title": item.title,
    }
    optional: dict[str, Any] = {
        "abstract": item.abstract,
        "DOI": item.doi,
        "container-title": item.publication_title,
        "page": None,
    }
    record.update({key: value for key, value in optional.items() if value})
    author = _parse_names(item.authors)
    if author:
        record["author"] = author
    editor = _parse_names(item.editors)
    if editor:
        record["editor"] = editor
    keyword = _parse_keywords(item.keywords)
    if keyword:
        record["keyword"] = keyword
    issued = _date_parts(item.publication_date)
    if issued:
        record["issued"] = {"date-parts": issued}
    return record


def _load_style(xml_text: str) -> CitationStylesStyle:
    return CitationStylesStyle(io.BytesIO(xml_text.encode("utf-8")))


def render_bibliography(
    csl_json: list[dict[str, Any]], style_xml: str, output_format: str = "text"
) -> list[str]:
    """Render CSL-JSON records to styled bibliography entries."""
    if not csl_json:
        return []
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


def render_citation(item: Item, style_xml: str, output_format: str = "text") -> str:
    """Render a single item to one formatted citation."""
    entries = render_bibliography([item_to_csl_json(item)], style_xml, output_format)
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


@lru_cache
def available_builtin_styles() -> dict[str, str]:
    """Return built-in styles whose CSL files are installed."""
    return {key: name for key, name in BUILTIN_STYLES.items() if builtin_style_xml(key)}


def is_valid_csl(xml_text: str) -> bool:
    """Return True when the text parses as a CSL style."""
    if not xml_text.strip():
        return False
    try:
        _load_style(xml_text)
    except Exception:
        return False
    return True
