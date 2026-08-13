from __future__ import annotations

from typing import Any

import bibtexparser
import rispy
from bibtexparser.bibdatabase import BibDatabase

from .models import Item

SUPPORTED_FORMATS = {"bibtex", "ris"}


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
        "publication_title": _text(
            entry.get("journal_name") or entry.get("secondary_title")
        ),
        "doi": _text(entry.get("doi")),
        "reference_type": _text(entry.get("type_of_reference")),
    }


def parse_bibliography(contents: str, file_format: str) -> tuple[list[dict], list[dict]]:
    if file_format not in SUPPORTED_FORMATS:
        raise ValueError("format must be bibtex or ris")
    try:
        raw_records = (
            bibtexparser.loads(contents).entries if file_format == "bibtex" else rispy.loads(contents)
        )
    except Exception as error:
        return [], [{"row": 0, "message": f"Cannot parse file: {error}"}]
    records = []
    errors = []
    for row, raw in enumerate(raw_records, start=1):
        record = _normalise(raw, file_format)
        if not record["title"]:
            errors.append({"row": row, "message": "Title is required"})
        records.append(record)
    if not raw_records:
        errors.append({"row": 0, "message": "The file contains no records"})
    return records, errors


def export_bibliography(items: list[Item], file_format: str) -> str:
    if file_format not in SUPPORTED_FORMATS:
        raise ValueError("format must be bibtex or ris")
    if file_format == "bibtex":
        entries = []
        for number, item in enumerate(items, start=1):
            entry = {
                "ID": f"quirebase-{number}",
                "ENTRYTYPE": (item.reference_type or "article").lower(),
                "title": item.title,
            }
            optional = {
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
        optional = {
            "abstract": item.abstract,
            "authors": item.authors.split("; ") if item.authors else None,
            "keywords": item.keywords.split("; ") if item.keywords else None,
            "year": item.publication_date,
            "journal_name": item.publication_title,
            "doi": item.doi,
        }
        record.update({key: value for key, value in optional.items() if value})
        records.append(record)
    return rispy.dumps(records)
