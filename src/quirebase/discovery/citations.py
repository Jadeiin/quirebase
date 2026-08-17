from __future__ import annotations

import io
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from quirebase.access.items import require_readable_item
from quirebase.core.errors import ResourceNotFound, ValidationFailure
from quirebase.discovery.bibliography import SUPPORTED_FORMATS, export_bibliography, first_url
from quirebase.discovery.lookup import normalize_reference_type
from quirebase.library.authors import parse_author_list_string
from quirebase.models import CitationStyle

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
    from citeproc_styles import get_style_filepath
except ImportError:  # optional `citation` extra is not installed
    get_style_filepath = None

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from quirebase.models import Item, User

BUILTIN_STYLES: dict[str, str] = {
    "apa": "APA 7th edition",
    "chicago-author-date": "Chicago (author-date)",
    "modern-language-association": "MLA",
    "harvard-cite-them-right": "Harvard",
    "american-medical-association": "Vancouver / AMA",
    "ieee": "IEEE",
}

# Keyed on canonical types only; callers normalize first (see
# normalize_reference_type), so the alias tables live in one place.
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


def item_to_csl_json(item: Item) -> dict[str, Any]:
    csl_type = REFERENCE_TYPE_TO_CSL.get(
        normalize_reference_type(item.reference_type) or "", "article"
    )
    record: dict[str, Any] = {
        "id": item.id,
        "type": csl_type,
        "title": item.title,
    }
    optional: dict[str, Any] = {
        "abstract": item.abstract,
        "DOI": item.doi,
        "container-title": item.publication_title,
        "container-title-short": item.journal_abbreviation,
        "volume": item.volume,
        "issue": item.issue,
        "page": item.pages,
        "publisher": item.publisher,
        "publisher-place": item.place_published,
        "URL": first_url(item.urls),
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


def _load_style(xml_text: str) -> Any:
    if CitationStylesStyle is None:
        raise ValidationFailure("CSL formatting requires the 'citation' extra")
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
        raise ValidationFailure("CSL formatting requires the 'citation' extra")
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


def resolve_style_xml(db: Session, user: User | None, style_key: str) -> str | None:
    builtin = builtin_style_xml(style_key)
    if builtin:
        return builtin
    if user is None:
        return None
    style = db.get(CitationStyle, style_key)
    if style is None or style.created_by != user.id:
        return None
    return style.csl_xml


def list_custom_citation_styles(db: Session, user: User) -> list[CitationStyle]:
    return list(
        db.scalars(
            select(CitationStyle)
            .where(CitationStyle.created_by == user.id)
            .order_by(CitationStyle.name)
        ).all()
    )


def create_custom_citation_style(db: Session, user: User, name: str, csl: str) -> CitationStyle:
    name = name.strip()
    if not name:
        raise ValidationFailure("style name is required")
    if len(name) > 120:
        name = name[:120]
    if not is_valid_csl(csl):
        raise ValidationFailure("the CSL text is not a valid citation style")
    style = CitationStyle(name=name, csl_xml=csl, created_by=user.id)
    db.add(style)
    db.commit()
    return style


def delete_custom_citation_style(db: Session, user: User, style_id: str) -> None:
    style = db.get(CitationStyle, style_id)
    if style is None or style.created_by != user.id:
        raise ResourceNotFound("citation style not found")
    db.delete(style)
    db.commit()


def format_csl_export(
    db: Session, user: User, items: list[Item], style_key: str = "apa"
) -> tuple[str, str, str]:
    style_xml = resolve_style_xml(db, user, style_key)
    if style_xml is None:
        raise ValidationFailure("unknown citation style")
    entries = render_bibliography([item_to_csl_json(item) for item in items], style_xml)
    return "\n\n".join(entries), "text/plain", "quirebase-citations.txt"


def format_standard_export(items: list[Item], file_format: str) -> tuple[str, str, str]:
    if file_format not in SUPPORTED_FORMATS:
        raise ValidationFailure("format must be bibtex, ris, or endnote")
    contents = export_bibliography(items, file_format)
    media_type = BIBLIOGRAPHY_MEDIA_TYPES[file_format]
    extension = BIBLIOGRAPHY_EXTENSIONS[file_format]
    filename = f"quirebase-export.{extension}"
    return contents, media_type, filename


def get_item_citation_response(
    db: Session, user: User, item_id: str, file_format: str, style_key: str = "apa"
) -> tuple[str, str, str]:
    item = require_readable_item(db, user, item_id)
    if file_format == "csl":
        return format_csl_export(db, user, [item], style_key=style_key)
    return format_standard_export([item], file_format)


def get_item_citation_text_response(
    db: Session, user: User, item_id: str, style_key: str = "apa", output: str = "text"
) -> tuple[str, str]:
    item = require_readable_item(db, user, item_id)
    style_xml = resolve_style_xml(db, user, style_key)
    if style_xml is None:
        raise ValidationFailure("unknown citation style")
    rendered = render_citation(item, style_xml, output_format=output)
    media_type = "text/html" if output == "html" else "text/plain"
    return rendered, media_type
