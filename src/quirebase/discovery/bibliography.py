from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bibtexparser
import rispy
from bibtexparser.bibdatabase import BibDatabase

if TYPE_CHECKING:
    from quirebase.models import Item

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

REFERENCE_TYPE_TO_ENDNOTE: dict[str, str] = {
    "article": "Journal Article",
    "journal-article": "Journal Article",
    "journal_article": "Journal Article",
    "jour": "Journal Article",
    "book": "Book",
    "chapter": "Book Section",
    "book-chapter": "Book Section",
    "book_section": "Book Section",
    "chap": "Book Section",
    "conference": "Conference Proceedings",
    "conference-paper": "Conference Proceedings",
    "conference_paper": "Conference Proceedings",
    "proceedings": "Conference Proceedings",
    "conf": "Conference Proceedings",
    "thesis": "Thesis",
    "dissertation": "Thesis",
    "thes": "Thesis",
    "report": "Report",
    "rprt": "Report",
    "webpage": "Web Page",
}

_ENDNOTE_TAGS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ@"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = "; ".join(str(part).strip() for part in value if str(part).strip())
    result = str(value).strip()
    return result or None


def _normalise(entry: dict[str, Any], file_format: str) -> dict[str, str | None]:
    if file_format == "bibtex":
        authors = _text(entry.get("author"))
        if authors:
            authors = "; ".join(part.strip() for part in authors.split(" and "))
        return {
            "title": _text(entry.get("title")),
            "abstract": _text(entry.get("abstract")),
            "authors": authors,
            "keywords": _text(entry.get("keywords")),
            "publication_date": _text(entry.get("date") or entry.get("year")),
            "publication_title": _text(entry.get("journal") or entry.get("booktitle")),
            "doi": _text(entry.get("doi")),
            "reference_type": _text(entry.get("ENTRYTYPE")),
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
            if current is None:
                continue
            if value:
                current.setdefault(tag, []).append(value)
    if current is not None:
        records.append(current)

    normalised = []
    for record in records:
        reference_type = _text(record.get("0", []))
        normalised.append({
            "title": _text(record.get("T", [])),
            "abstract": _text(record.get("X", [])),
            "authors": _text(record.get("A", [])),
            "editors": _text(record.get("E", [])),
            "keywords": _text(record.get("K", [])),
            "publication_date": _text(record.get("D", [])),
            "publication_title": _text(record.get("J", []) or record.get("B", [])),
            "doi": _text(record.get("@", [])),
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


def _export_endnote(items: list[Item]) -> str:
    lines: list[str] = []
    for item in items:
        reference_type = REFERENCE_TYPE_TO_ENDNOTE.get(
            (item.reference_type or "article").lower(), "Journal Article"
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
            lines.append(f"%@ {item.doi}")
        lines.extend(
            f"%K {keyword.strip()}"
            for keyword in (item.keywords or "").split(";")
            if keyword.strip()
        )
        if item.abstract:
            lines.append(f"%X {item.abstract}")
        lines.append("")
    return "\n".join(lines)


def export_bibliography(items: list[Item], file_format: str) -> str:
    if file_format not in SUPPORTED_FORMATS:
        raise ValueError("format must be bibtex, ris or endnote")
    if file_format == "endnote":
        return _export_endnote(items)
    if file_format == "bibtex":
        entries = []
        for number, item in enumerate(items, start=1):
            entry = {
                "ID": f"quirebase-{number}",
                "ENTRYTYPE": (item.reference_type or "article").lower(),
                "title": item.title,
            }
            optional: dict[str, Any] = {
                "abstract": item.abstract,
                "author": item.authors.replace("; ", " and ") if item.authors else None,
                "keywords": item.keywords,
                "year": item.publication_date,
                "journal": item.publication_title,
                "doi": item.doi,
            }
            entry.update({key: value for key, value in optional.items() if value})
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
            "abstract": item.abstract,
            "authors": item.authors.split("; ") if item.authors else None,
            "keywords": item.keywords.split("; ") if item.keywords else None,
            "year": item.publication_date,
            "journal_name": item.publication_title,
            "doi": item.doi,
        }
        record.update({key: value for key, value in ris_optional.items() if value})
        records.append(record)
    return rispy.dumps(records)
