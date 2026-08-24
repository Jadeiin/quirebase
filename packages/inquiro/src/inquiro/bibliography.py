from __future__ import annotations

import json
import re
from contextlib import suppress
from typing import Any

import bibtexparser
import rispy
from bibtexparser.bibdatabase import BibDatabase

from inquiro.parsing import normalize_reference_type

SUPPORTED_FORMATS = {"bibtex", "ris", "endnote"}

ENDNOTE_TYPE_TO_REFERENCE: dict[str, str] = {
    "Journal Article": "journal-article",
    "Book": "book",
    "Book Section": "chapter",
    "Book Chapter": "chapter",
    "Conference Proceedings": "conference-paper",
    "Conference Paper": "conference-paper",
    "Thesis": "thesis",
    "Dissertation": "thesis",
    "Report": "report",
    "Web Page": "webpage",
    "Generic": "article",
}

# Maps are keyed on canonical types only; callers normalize first (see
# normalize_reference_type), so the alias tables live in one place.
REFERENCE_TYPE_TO_ENDNOTE: dict[str, str] = {
    "article": "Journal Article",
    "book": "Book",
    "chapter": "Book Section",
    "conference": "Conference Proceedings",
    "thesis": "Thesis",
    "report": "Report",
    "webpage": "Web Page",
}

_BIBTEX_FIELD_NAME = re.compile(r"[^A-Za-z0-9_]")


def _safe_bibtex_field_name(key: Any) -> str | None:
    field = _BIBTEX_FIELD_NAME.sub("_", str(key).strip()).strip("_")
    if not field:
        return None
    return f"field_{field}" if field[0].isdigit() else field


def _add_bibtex_extra(extras: dict[str, str], reserved: set[str], key: Any, value: str) -> None:
    field = _safe_bibtex_field_name(key)
    if not field or field.casefold() in reserved:
        return
    candidate = field
    suffix = 2
    existing = {existing_field.casefold() for existing_field in extras}
    while candidate.casefold() in existing:
        candidate = f"{field}_{suffix}"
        suffix += 1
    extras[candidate] = value


REFERENCE_TYPE_TO_BIBTEX: dict[str, str] = {
    "article": "article",
    "book": "book",
    "chapter": "incollection",
    "conference": "inproceedings",
    "preprint": "misc",
    "thesis": "phdthesis",
    "report": "techreport",
    "generic": "misc",
    "unpublished": "unpublished",
    "webpage": "misc",
}

_ENDNOTE_TAGS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ@"

_YEAR_PATTERN = re.compile(r"\b(19\d\d|20\d\d)\b")


def extract_year(publication_date: str | None) -> str | None:
    if not publication_date:
        return None
    match = _YEAR_PATTERN.search(publication_date)
    return match.group(1) if match else None


def first_url(urls: str | None) -> str | None:
    if not urls:
        return None
    return urls.splitlines()[0].strip()


def _protect_bibtex_case(value: str) -> str:
    """Protect uppercase runs without obscuring the field's BibTeX structure."""
    protected: list[str] = []
    depth = 0
    position = 0
    while position < len(value):
        character = value[position]
        if character == "{":
            depth += 1
            protected.append(character)
            position += 1
        elif character == "}":
            depth = max(0, depth - 1)
            protected.append(character)
            position += 1
        elif character == "\\":
            command_end = position + 1
            while command_end < len(value) and value[command_end].isalpha():
                command_end += 1
            if command_end == position + 1 and command_end < len(value):
                command_end += 1
            protected.append(value[position:command_end])
            position = command_end
        elif depth == 0 and character.isalpha() and character.isupper():
            run_end = position + 1
            while run_end < len(value) and value[run_end].isalpha() and value[run_end].isupper():
                run_end += 1
            protected.append(f"{{{value[position:run_end]}}}")
            position = run_end
        else:
            protected.append(character)
            position += 1
    return "".join(protected)


def _bibtex_extra_fields(
    item: Any, *, include_identifiers: bool, include_custom_fields: bool
) -> dict[str, str]:
    extras: dict[str, str] = {}
    reserved = {
        "abstract",
        "author",
        "doi",
        "entrytype",
        "id",
        "journal",
        "keywords",
        "number",
        "pages",
        "publisher",
        "title",
        "url",
        "volume",
        "year",
    }
    if include_identifiers:
        identifiers: dict[str, Any] = {}
        if getattr(item, "identifiers", None):
            with suppress(json.JSONDecodeError):
                parsed = json.loads(item.identifiers)
                if isinstance(parsed, dict):
                    identifiers.update(parsed)
        if getattr(item, "doi", None):
            identifiers["doi"] = item.doi
        for key, value in identifiers.items():
            if value not in (None, ""):
                _add_bibtex_extra(extras, reserved, key, str(value))
    if include_custom_fields and getattr(item, "custom_fields", None):
        with suppress(json.JSONDecodeError):
            parsed = json.loads(item.custom_fields)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    if value not in (None, ""):
                        _add_bibtex_extra(
                            extras,
                            reserved,
                            key,
                            json.dumps(value, ensure_ascii=False)
                            if isinstance(value, (dict, list))
                            else str(value),
                        )
    return extras


def _text(value: Any, separator: str = "; ") -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = separator.join(str(part).strip() for part in value if str(part).strip())
    result = str(value).strip()
    return result or None


def _normalise(entry: dict[str, Any], file_format: str) -> dict[str, str | None]:
    if file_format == "bibtex":
        authors = _text(entry.get("author"))
        if authors:
            authors = "; ".join(part.strip() for part in authors.split(" and "))
        known_fields = {
            "abstract",
            "author",
            "booktitle",
            "date",
            "doi",
            "editor",
            "entrytype",
            "id",
            "journal",
            "keywords",
            "number",
            "pages",
            "publisher",
            "title",
            "url",
            "volume",
            "year",
        }
        identifiers: dict[str, str] = {}
        custom_fields: dict[str, str] = {}
        for key, value in entry.items():
            normalized_key = key.casefold()
            if normalized_key in {"openalex", "arxiv", "pmid", "pmc", "issn", "isbn"}:
                if text_value := _text(value):
                    identifiers[normalized_key] = text_value
            elif normalized_key not in known_fields and (text_value := _text(value)):
                custom_fields[key] = text_value
        return {
            "title": _text(entry.get("title")),
            "abstract": _text(entry.get("abstract")),
            "authors": authors,
            "keywords": _text(entry.get("keywords")),
            "publication_date": _text(entry.get("date") or entry.get("year")),
            "publication_title": _text(entry.get("journal") or entry.get("booktitle")),
            "doi": _text(entry.get("doi")),
            "reference_type": _text(entry.get("ENTRYTYPE")),
            "bibtex_id": _text(entry.get("ID")),
            "identifiers": json.dumps(identifiers, ensure_ascii=False) if identifiers else None,
            "custom_fields": json.dumps(custom_fields, ensure_ascii=False)
            if custom_fields
            else None,
        }
    return {
        "title": _text(entry.get("title") or entry.get("primary_title")),
        "abstract": _text(entry.get("abstract") or entry.get("notes_abstract")),
        "authors": _text(entry.get("authors") or entry.get("first_authors")),
        "keywords": _text(entry.get("keywords")),
        "publication_date": _text(entry.get("publication_year") or entry.get("year")),
        "publication_title": _text(entry.get("journal_name") or entry.get("secondary_title")),
        "doi": _text(entry.get("doi")),
        "reference_type": _text(entry.get("type_of_reference")),
    }


def _parse_endnote_records(contents: str) -> list[dict[str, str | None]]:
    records: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] | None = None
    last_tag: str | None = None
    for raw_line in contents.splitlines():
        line = raw_line.rstrip("\r")
        if not line.strip():
            continue
        if len(line) >= 3 and line[0] == "%" and line[1] in _ENDNOTE_TAGS and line[2] in " \t":
            tag = line[1].upper()
            value = line[3:].strip()
            if tag == "0":
                if current is not None:
                    records.append(current)
                current = {}
                last_tag = None
            if current is None:
                continue
            if value:
                current.setdefault(tag, []).append(value)
                last_tag = tag
            else:
                last_tag = tag
        elif current is not None and last_tag is not None:
            continuation = line.strip()
            if continuation:
                if current.get(last_tag):
                    sep = "\n" if last_tag == "X" else " "
                    current[last_tag][-1] = f"{current[last_tag][-1]}{sep}{continuation}"
                else:
                    current.setdefault(last_tag, []).append(continuation)
    if current is not None:
        records.append(current)

    normalised = []
    for record in records:
        reference_type = _text(record.get("0", []))
        normalised.append({
            "title": _text(record.get("T", [])),
            "abstract": _text(record.get("X", []), separator="\n"),
            "authors": _text(record.get("A", [])),
            "editors": _text(record.get("E", [])),
            "keywords": _text(record.get("K", [])),
            "publication_date": _text(record.get("D", [])),
            "publication_title": _text(record.get("J", []) or record.get("B", [])),
            "doi": _text(record.get("R", [])),
            "reference_type": (
                ENDNOTE_TYPE_TO_REFERENCE.get(reference_type, reference_type)
                if reference_type
                else None
            ),
        })
    return normalised


def parse_bibliography(contents: str, file_format: str) -> tuple[list[dict], list[dict]]:
    if file_format not in SUPPORTED_FORMATS:
        raise ValueError("format must be bibtex, ris or endnote")
    try:
        if file_format == "bibtex":
            raw_records = bibtexparser.loads(contents).entries
        elif file_format == "ris":
            raw_records = rispy.loads(contents)
        else:
            raw_records = _parse_endnote_records(contents)
    except Exception as error:
        return [], [{"row": 0, "message": f"Cannot parse file: {error}"}]
    records = []
    errors = []
    for row, raw in enumerate(raw_records, start=1):
        record = raw if file_format == "endnote" else _normalise(raw, file_format)
        if not record["title"]:
            errors.append({"row": row, "message": "Title is required"})
        records.append(record)
    if not raw_records:
        errors.append({"row": 0, "message": "The file contains no records"})
    return records, errors


def _export_endnote(items: list[Any], *, include_abstract: bool = True) -> str:
    lines: list[str] = []
    for item in items:
        reference_type = REFERENCE_TYPE_TO_ENDNOTE.get(
            normalize_reference_type(item.reference_type) or "article", "Journal Article"
        )
        lines.append(f"%0 {reference_type}")
        lines.extend(
            f"%A {author.strip()}" for author in (item.authors or "").split(";") if author.strip()
        )
        lines.extend(
            f"%E {editor.strip()}" for editor in (item.editors or "").split(";") if editor.strip()
        )
        if item.title:
            lines.append(f"%T {item.title}")
        if item.publication_title:
            lines.append(f"%J {item.publication_title}")
        if item.publication_date:
            lines.append(f"%D {item.publication_date}")
        if item.doi:
            lines.append(f"%R {item.doi}")
        lines.extend(
            f"%K {keyword.strip()}"
            for keyword in (item.keywords or "").split(";")
            if keyword.strip()
        )
        if include_abstract and item.abstract:
            lines.append(f"%X {item.abstract}")
        lines.append("")
    return "\n".join(lines)


def export_bibliography(
    items: list[Any],
    file_format: str,
    *,
    include_abstract: bool = True,
    preserve_case: bool = False,
    abbreviate_journal: bool = False,
    include_identifiers: bool = False,
    include_custom_fields: bool = False,
) -> str:
    if file_format not in SUPPORTED_FORMATS:
        raise ValueError("format must be bibtex, ris or endnote")
    if file_format == "endnote":
        return _export_endnote(items, include_abstract=include_abstract)
    if file_format == "bibtex":
        entries = []
        for number, item in enumerate(items, start=1):
            entry_type = (
                item.bibtex_type
                or REFERENCE_TYPE_TO_BIBTEX.get(
                    normalize_reference_type(item.reference_type) or "", "article"
                )
            ).lower()
            entry = {
                "ID": item.bibtex_id or f"quirebase-{number}",
                "ENTRYTYPE": entry_type,
                "title": item.title,
            }
            optional: dict[str, Any] = {
                "abstract": item.abstract if include_abstract else None,
                "author": item.authors.replace("; ", " and ") if item.authors else None,
                "keywords": item.keywords,
                "year": extract_year(item.publication_date) or item.publication_date,
                "journal": item.journal_abbreviation
                if abbreviate_journal and item.journal_abbreviation
                else item.publication_title,
                "volume": item.volume,
                "number": item.issue,
                "pages": item.pages,
                "publisher": item.publisher,
                "doi": item.doi,
                "url": first_url(item.urls),
            }
            entry.update({key: value for key, value in optional.items() if value})
            extra_fields = _bibtex_extra_fields(
                item,
                include_identifiers=include_identifiers,
                include_custom_fields=include_custom_fields,
            )
            entry.update(extra_fields)
            if preserve_case:
                for field in ("title", "booktitle", "series"):
                    if value := entry.get(field):
                        entry[field] = _protect_bibtex_case(value)
            entries.append(entry)
        database = BibDatabase()
        database.entries = entries
        return bibtexparser.dumps(database)
    records = []
    for item in items:
        record: dict[str, Any] = {
            "type_of_reference": (item.reference_type or "JOUR").upper(),
            "title": item.title,
        }
        ris_optional: dict[str, Any] = {
            "abstract": item.abstract if include_abstract else None,
            "authors": item.authors.split("; ") if item.authors else None,
            "keywords": item.keywords.split("; ") if item.keywords else None,
            "year": item.publication_date,
            "journal_name": item.publication_title,
            "doi": item.doi,
        }
        record.update({key: value for key, value in ris_optional.items() if value})
        records.append(record)
    return rispy.dumps(records)
