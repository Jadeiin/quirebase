"""Bibliography interchange: parse and export BibTeX, BibLaTeX, RIS and EndNote."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from typing import Any

import rispy
from bibtexparser import Library as _V2Library
from bibtexparser import parse_string as _parse_bibtex_string
from bibtexparser import write_string as _write_bibtex_string
from bibtexparser.middlewares import (
    AddEnclosingMiddleware,
    MonthAbbreviationMiddleware,
    MonthLongStringMiddleware,
    RemoveEnclosingMiddleware,
    ResolveStringReferencesMiddleware,
    SeparateCoAuthors,
)
from bibtexparser.model import Entry as _V2Entry
from bibtexparser.model import Field as _V2Field
from bibtexparser.writer import BibtexFormat as _V2BibtexFormat

from inquiro.bibliography.keys import (
    evaluate_citation_key_formula,
    extract_year,
    suffixed_citation_key,
    validate_citation_key_formula,
)
from inquiro.bibliography.options import BibliographyExportOptions
from inquiro.bibliography.records import BibliographyRecord, Contributor
from inquiro.canonical import normalize_reference_type
from inquiro.richtext import convert_rich_text

SUPPORTED_FORMATS = {"bibtex", "biblatex", "ris", "endnote"}

BIBLIOGRAPHY_MEDIA_TYPES: dict[str, str] = {
    "bibtex": "application/x-bibtex",
    "biblatex": "application/x-bibtex",
    "ris": "application/x-research-info-systems",
    "endnote": "application/x-endnote-refer",
}

BIBLIOGRAPHY_EXTENSIONS: dict[str, str] = {
    "bibtex": "bib",
    "biblatex": "bib",
    "ris": "ris",
    "endnote": "enw",
}

_BIBTEX_PARSE_STACK = (
    ResolveStringReferencesMiddleware(allow_inplace_modification=False),
    RemoveEnclosingMiddleware(allow_inplace_modification=False),
    SeparateCoAuthors(allow_inplace_modification=False),
)
_BIBTEX_WRITE_STACK = (
    AddEnclosingMiddleware(
        reuse_previous_enclosing=False,
        enclose_integers=True,
        default_enclosing="{",
        allow_inplace_modification=False,
    ),
)
_BIBTEX_FORMAT = _V2BibtexFormat()
_BIBTEX_FORMAT.indent = "    "
_BIBTEX_FORMAT.block_separator = "\n"

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
    "dataset": "misc",
    "patent": "misc",
}
REFERENCE_TYPE_TO_BIBLATEX: dict[str, str] = {
    **REFERENCE_TYPE_TO_BIBTEX,
    "preprint": "online",
    "webpage": "online",
    "dataset": "dataset",
    "patent": "patent",
    "report": "report",
    "thesis": "thesis",
}
ENDNOTE_TYPE_TO_REFERENCE = {
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
REFERENCE_TYPE_TO_ENDNOTE = {
    "article": "Journal Article",
    "book": "Book",
    "chapter": "Book Section",
    "conference": "Conference Proceedings",
    "thesis": "Thesis",
    "report": "Report",
    "webpage": "Web Page",
}
REFERENCE_TYPE_TO_RIS = {
    "article": "JOUR",
    "book": "BOOK",
    "chapter": "CHAP",
    "conference": "CPAPER",
    "dataset": "DATA",
    "generic": "GEN",
    "patent": "PAT",
    "preprint": "UNPB",
    "report": "RPRT",
    "thesis": "THES",
    "unpublished": "UNPB",
    "webpage": "ELEC",
}
RIS_TYPE_TO_REFERENCE = {
    "JOUR": "article",
    "BOOK": "book",
    "CHAP": "chapter",
    "CPAPER": "conference",
    "DATA": "dataset",
    "GEN": "generic",
    "PAT": "patent",
    "UNPB": "unpublished",
    "RPRT": "report",
    "THES": "thesis",
    "ELEC": "webpage",
}

_ENDNOTE_TAGS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ@"
_SAFE_FIELD_NAME = re.compile(r"[^A-Za-z0-9_]")
_BIBLIOGRAPHY_IDENTIFIER_PROVIDERS = (
    "openalex",
    "arxiv",
    "pmid",
    "pmc",
    "issn",
    "isbn",
    "bibcode",
    "article_number",
)


class _BibTeXExpressionError(ValueError):
    """A concatenated BibTeX value cannot be resolved without data loss."""


def _bibtex_month_macros() -> dict[str, str]:
    """Build BibTeX's predefined month strings from bibtexparser's canonical mapping."""
    abbreviate = MonthAbbreviationMiddleware().resolve_month_field_val
    long_name = MonthLongStringMiddleware().resolve_month_field_val
    macros: dict[str, str] = {}
    for month_number in range(1, 13):
        abbreviation, _ = abbreviate(_V2Field("month", month_number))
        full_name, _ = long_name(_V2Field("month", month_number))
        macros[str(abbreviation)] = str(full_name)
    return macros


_BIBTEX_MONTH_MACROS = _bibtex_month_macros()


def _split_bibtex_concatenation(value: str) -> list[str] | None:
    parts: list[str] = []
    start = 0
    depth = 0
    quoted = False
    escaped = False
    found_separator = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if quoted:
            if character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                raise _BibTeXExpressionError("unmatched closing brace")
        elif character == "#" and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
            found_separator = True
    if quoted or depth:
        raise _BibTeXExpressionError("unclosed quoted or braced value")
    if not found_separator:
        return None
    parts.append(value[start:].strip())
    if any(not part for part in parts):
        raise _BibTeXExpressionError("empty concatenation component")
    return parts


def _resolve_bibtex_concatenations(
    library: _V2Library,
) -> tuple[set[int], list[dict[str, Any]]]:
    """Resolve ``#`` expressions omitted by bibtexparser v2's string middleware."""
    strings = {key.casefold(): block for key, block in library.strings_dict.items()}
    resolved_strings: dict[str, str] = {}

    def resolve_macro(name: str, resolving: frozenset[str]) -> str:
        normalized = name.casefold()
        if normalized in resolved_strings:
            return resolved_strings[normalized]
        block = strings.get(normalized)
        if block is None:
            predefined = _BIBTEX_MONTH_MACROS.get(normalized)
            if predefined is None:
                raise _BibTeXExpressionError(f"undefined string macro {name!r}")
            return predefined
        if normalized in resolving:
            raise _BibTeXExpressionError(f"cyclic string macro {name!r}")
        enclosing = block.parser_metadata.get("removed_enclosing")
        value = str(block.value)
        if enclosing in {"{", '"'}:
            resolved = value
        else:
            resolved = resolve_expression(value, resolving | {normalized})
        resolved_strings[normalized] = resolved
        return resolved

    def resolve_component(component: str, resolving: frozenset[str]) -> str:
        if component.startswith("{") and component.endswith("}"):
            return component[1:-1]
        if component.startswith('"') and component.endswith('"'):
            return component[1:-1]
        if component.isdigit():
            return component
        return resolve_macro(component, resolving)

    def resolve_expression(value: str, resolving: frozenset[str] = frozenset()) -> str:
        parts = _split_bibtex_concatenation(value)
        if parts is None:
            return resolve_component(value.strip(), resolving)
        return "".join(resolve_component(part, resolving) for part in parts)

    invalid_entries: set[int] = set()
    errors: list[dict[str, Any]] = []
    for entry in library.entries:
        removed = entry.parser_metadata.get("removed_enclosing", {})
        for field in entry.fields:
            if removed.get(field.key) != "no-enclosing":
                continue
            try:
                parts = _split_bibtex_concatenation(str(field.value))
                if parts is not None:
                    field.value = resolve_expression(str(field.value))
            except _BibTeXExpressionError as error:
                invalid_entries.add(id(entry))
                errors.append({
                    "row": (entry.start_line or 0) + 1,
                    "message": f"Cannot parse record: {field.key}: {error}",
                })
                break
    return invalid_entries, errors


def first_url(urls: str | None) -> str | None:
    return urls.splitlines()[0].strip() or None if urls else None


def _protect_case(value: str) -> str:
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
            end = position + 1
            while end < len(value) and value[end].isalpha():
                end += 1
            end = max(end, position + 2)
            protected.append(value[position:end])
            position = end
        elif depth == 0 and character.isalpha() and character.isupper():
            end = position + 1
            while end < len(value) and value[end].isalpha() and value[end].isupper():
                end += 1
            protected.append(f"{{{value[position:end]}}}")
            position = end
        else:
            protected.append(character)
            position += 1
    return "".join(protected)


def _latex_text(value: str, encoding: str) -> str:
    return convert_rich_text(
        value,
        source="text",
        target="latex",
        latex_encoding="latex" if encoding == "latex" else "unicode",
    )


def _balance_literal_braces(value: str) -> str:
    """Escape literal braces left unmatched after balanced TeX groups are closed."""

    rendered = list(value)
    open_positions: list[int] = []
    position = 0
    while position < len(value):
        character = value[position]
        if character == "\\" and position + 1 < len(value):
            position += 2
            continue
        if character == "{":
            open_positions.append(position)
        elif character == "}" and open_positions:
            open_positions.pop()
        elif character == "}":
            rendered[position] = "\\}"
        position += 1
    for open_position in reversed(open_positions):
        rendered[open_position] = "\\{"
    return "".join(rendered)


def _latex_decode(value: str) -> str:
    return convert_rich_text(value, source="latex", target="text")


def _safe_field_name(value: Any) -> str | None:
    field_name = _SAFE_FIELD_NAME.sub("_", str(value).strip()).strip("_")
    if not field_name:
        return None
    return f"field_{field_name}" if field_name[0].isdigit() else field_name


def _add_disambiguated_field(
    fields: dict[str, str | None],
    existing: set[str],
    name: Any,
    value: str,
) -> None:
    base = _safe_field_name(name)
    if not base:
        return
    candidate = base
    suffix = 2
    while candidate.casefold() in existing:
        candidate = f"{base}_{suffix}"
        suffix += 1
    fields[candidate] = value
    existing.add(candidate.casefold())


def _separated_names(entry: _V2Entry) -> dict[str, list[str]]:
    """Return author/editor fields already split into individual name strings."""
    names: dict[str, list[str]] = {}
    for role in ("author", "editor"):
        field = entry.fields_dict.get(role)
        if field is None:
            continue
        value = field.value
        if isinstance(value, list):
            names[role] = [str(item) for item in value]
        elif value is not None:
            names[role] = [str(value)]
    return names


def _contributors(people: list[str] | None) -> tuple[Contributor, ...]:
    return tuple(Contributor.parse(person) for person in people or [])


def _person_name(contributor: Contributor, encoding: str) -> str:
    family = _latex_text(contributor.family_name, encoding)
    if contributor.literal:
        return f"{{{family}}}"
    return f"{family}, {_latex_text(contributor.given_name or '', encoding)}"


def _bib_record(citation_key: str, entry: _V2Entry) -> BibliographyRecord:
    raw_fields = {
        key.casefold(): (value.value if isinstance(value.value, str) else None)
        for key, value in entry.fields_dict.items()
    }
    name_fields = _separated_names(entry)
    fields = {key: _latex_decode(value) for key, value in raw_fields.items() if value is not None}
    known = {
        "abstract",
        "archiveprefix",
        "booktitle",
        "date",
        "doi",
        "eprint",
        "journal",
        "journaltitle",
        "keywords",
        "location",
        "number",
        "pages",
        "publisher",
        "title",
        "url",
        "volume",
        "year",
        "address",
    }
    identifiers: list[tuple[str, str]] = []
    if fields.get("eprint"):
        identifiers.append(((fields.get("archiveprefix") or "eprint").lower(), fields["eprint"]))
    identifiers.extend(
        (name, fields[name]) for name in _BIBLIOGRAPHY_IDENTIFIER_PROVIDERS if fields.get(name)
    )
    identifier_names = {name for name, _value in identifiers}
    custom = tuple(
        (key, value)
        for key, value in fields.items()
        if key not in known and key not in identifier_names
    )
    normalized_type = normalize_reference_type(entry.entry_type) or entry.entry_type
    return BibliographyRecord(
        citation_key=citation_key,
        reference_type=normalized_type,
        bibtex_type=entry.entry_type,
        title=convert_rich_text(raw_fields.get("title"), source="latex", target="html"),
        authors=_contributors(name_fields.get("author")),
        editors=_contributors(name_fields.get("editor")),
        abstract=(
            convert_rich_text(raw_fields["abstract"], source="latex", target="html")
            if raw_fields.get("abstract")
            else None
        ),
        keywords=tuple(
            part.strip() for part in fields.get("keywords", "").split(";") if part.strip()
        ),
        publication_date=fields.get("date") or fields.get("year"),
        publication_title=fields.get("journaltitle") or fields.get("journal"),
        book_title=fields.get("booktitle"),
        volume=fields.get("volume"),
        issue=fields.get("number"),
        pages=fields.get("pages"),
        publisher=fields.get("publisher"),
        location=fields.get("location") or fields.get("address"),
        doi=fields.get("doi"),
        urls=(fields["url"],) if fields.get("url") else (),
        identifiers=tuple(identifiers),
        custom_fields=custom,
    )


def _ris_record(entry: dict[str, Any]) -> BibliographyRecord:
    def text(value: Any) -> str | None:
        if isinstance(value, list):
            value = "; ".join(str(part) for part in value)
        return str(value).strip() or None if value is not None else None

    authors = entry.get("authors") or entry.get("first_authors") or []
    if isinstance(authors, str):
        authors = [authors]
    raw_type = text(entry.get("type_of_reference")) or "JOUR"
    return BibliographyRecord(
        citation_key=None,
        reference_type=RIS_TYPE_TO_REFERENCE.get(raw_type, raw_type),
        title=text(entry.get("title") or entry.get("primary_title")) or "",
        authors=tuple(Contributor.parse(value) for value in authors),
        abstract=text(entry.get("abstract") or entry.get("notes_abstract")),
        keywords=tuple(entry.get("keywords") or ()),
        publication_date=text(entry.get("publication_year") or entry.get("year")),
        publication_title=text(entry.get("journal_name") or entry.get("secondary_title")),
        doi=text(entry.get("doi")),
        urls=tuple(entry.get("urls") or ()),
    )


def _parse_endnote_records(contents: str) -> list[dict[str, list[str]]]:
    records: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] | None = None
    last_tag: str | None = None
    for raw_line in contents.splitlines():
        line = raw_line.rstrip("\r")
        if not line.strip():
            continue
        if len(line) >= 3 and line[0] == "%" and line[1] in _ENDNOTE_TAGS and line[2].isspace():
            tag, value = line[1].upper(), line[3:].strip()
            if tag == "0":
                if current is not None:
                    records.append(current)
                current = {}
            if current is not None and value:
                current.setdefault(tag, []).append(value)
            last_tag = tag
        elif current is not None and last_tag:
            continuation = line.strip()
            if continuation and current.get(last_tag):
                separator = "\n" if last_tag == "X" else " "
                current[last_tag][-1] += separator + continuation
    if current is not None:
        records.append(current)
    return records


def _endnote_record(entry: dict[str, list[str]]) -> BibliographyRecord:
    def first(tag: str) -> str | None:
        return entry.get(tag, [None])[0]

    raw_type = first("0")
    return BibliographyRecord(
        citation_key=None,
        reference_type=ENDNOTE_TYPE_TO_REFERENCE.get(raw_type or "", raw_type or "article"),
        title=first("T") or "",
        authors=tuple(Contributor.parse(value) for value in entry.get("A", [])),
        editors=tuple(Contributor.parse(value) for value in entry.get("E", [])),
        abstract="\n".join(entry.get("X", [])) or None,
        keywords=tuple(entry.get("K", [])),
        publication_date=first("D"),
        publication_title=first("J") or first("B"),
        doi=first("R"),
        urls=tuple(entry.get("U", [])),
    )


def parse_bibliography_records(
    contents: str, file_format: str
) -> tuple[list[BibliographyRecord], list[dict[str, Any]]]:
    if file_format not in SUPPORTED_FORMATS:
        raise ValueError("format must be bibtex, biblatex, ris or endnote")
    library = None
    concatenation_errors: list[dict[str, Any]] = []
    try:
        if file_format in {"bibtex", "biblatex"}:
            library = _parse_bibtex_string(
                contents,
                parse_stack=_BIBTEX_PARSE_STACK,
            )
            invalid_entries, concatenation_errors = _resolve_bibtex_concatenations(library)
            records = [
                _bib_record(entry.key, entry)
                for entry in library.entries
                if id(entry) not in invalid_entries
            ]
        elif file_format == "ris":
            records = [_ris_record(entry) for entry in rispy.loads(contents)]
        else:
            records = [_endnote_record(entry) for entry in _parse_endnote_records(contents)]
    except Exception as error:
        return [], [{"row": 0, "message": f"Cannot parse file: {error}"}]
    errors = (
        [
            {
                "row": (block.start_line or 0) + 1,
                "message": (
                    "Cannot parse record: "
                    f"{getattr(block.error, 'abort_reason', None) or str(block.error) or 'invalid BibTeX'}"
                ),
            }
            for block in library.failed_blocks
        ]
        if library is not None
        else []
    )
    errors.extend(concatenation_errors)
    errors.extend([
        {"row": row, "message": "Title is required"}
        for row, record in enumerate(records, start=1)
        if not convert_rich_text(record.title, source="html", target="text")
    ])
    if not records:
        errors.append({"row": 0, "message": "The file contains no records"})
    return records, errors


def _sort_records(records: list[BibliographyRecord], sort_by: str) -> list[BibliographyRecord]:
    if sort_by == "input":
        return records
    keys = {
        "citation_key": lambda record: (record.citation_key or "").casefold(),
        "author": lambda record: record.authors[0].family_name.casefold() if record.authors else "",
        "year": lambda record: extract_year(record.publication_date) or "",
        "title": lambda record: convert_rich_text(
            record.title, source="html", target="text"
        ).casefold(),
    }
    return sorted(records, key=keys[sort_by])


def _entry_for_record(
    record: BibliographyRecord,
    file_format: str,
    options: BibliographyExportOptions,
) -> tuple[str, dict[str, str]]:
    normalized_type = normalize_reference_type(record.reference_type) or "generic"
    type_map = REFERENCE_TYPE_TO_BIBLATEX if file_format == "biblatex" else REFERENCE_TYPE_TO_BIBTEX
    entry_type = record.bibtex_type or type_map.get(normalized_type, "misc")
    entry_type = entry_type.lower()
    journal = record.publication_title
    if options.journal_mode == "abbreviated":
        journal = record.journal_abbreviation
    elif options.journal_mode == "prefer_abbreviated":
        journal = record.journal_abbreviation or record.publication_title
    include_url = options.url_policy == "include" or (
        options.url_policy == "omit_when_doi" and not record.doi
    )
    title = convert_rich_text(
        record.title,
        source="html",
        target="latex",
        latex_encoding=options.encoding,
    )
    if options.preserve_case:
        title = _protect_case(title)
    title = _balance_literal_braces(title)
    abstract = (
        convert_rich_text(
            record.abstract,
            source="html",
            target="latex",
            latex_encoding=options.encoding,
        )
        if options.include_abstract and record.abstract
        else None
    )
    fields: dict[str, str | None] = {
        "title": title,
        "abstract": abstract,
        "keywords": "; ".join(record.keywords) or None,
        ("date" if file_format == "biblatex" else "year"): (
            record.publication_date
            if file_format == "biblatex"
            else extract_year(record.publication_date) or record.publication_date
        ),
        ("journaltitle" if file_format == "biblatex" else "journal"): journal,
        "booktitle": record.book_title,
        "volume": record.volume,
        "number": record.issue,
        "pages": record.pages,
        "publisher": record.publisher,
        ("location" if file_format == "biblatex" else "address"): record.location,
        "doi": record.doi if options.doi_policy == "include" else None,
        "url": record.urls[0] if record.urls and include_url else None,
    }
    existing = {name.casefold() for name in fields}
    if options.include_identifiers:
        included_identifiers: set[str] = set()
        for name, value in record.identifiers:
            provider = name.strip().casefold()
            if (
                provider not in _BIBLIOGRAPHY_IDENTIFIER_PROVIDERS
                or provider in included_identifiers
            ):
                continue
            included_identifiers.add(provider)
            if provider == "arxiv" and file_format == "biblatex":
                fields.update(eprint=value, archiveprefix="arXiv")
                existing.update(("eprint", "archiveprefix"))
            else:
                fields[provider] = value
                existing.add(provider)
    if options.include_custom_fields:
        for name, value in record.custom_fields:
            _add_disambiguated_field(fields, existing, name, value)
    excluded = {name.casefold() for name in options.excluded_fields}
    encoded_fields = {
        name: value if name in {"title", "abstract"} else _latex_text(value, options.encoding)
        for name, value in fields.items()
        if value and name.casefold() not in excluded
    }
    persons: dict[str, str] = {}
    if record.authors and "author" not in excluded:
        persons["author"] = " and ".join(
            _person_name(person, options.encoding) for person in record.authors
        )
    if record.editors and "editor" not in excluded:
        persons["editor"] = " and ".join(
            _person_name(person, options.encoding) for person in record.editors
        )
    return entry_type, {**encoded_fields, **persons}


def _excluded(options: BibliographyExportOptions, *names: str) -> bool:
    excluded = {name.casefold() for name in options.excluded_fields}
    return any(name.casefold() in excluded for name in names)


def _export_journal(record: BibliographyRecord, options: BibliographyExportOptions) -> str | None:
    if options.journal_mode == "abbreviated":
        return record.journal_abbreviation
    if options.journal_mode == "prefer_abbreviated":
        return record.journal_abbreviation or record.publication_title
    return record.publication_title


def _include_url(record: BibliographyRecord, options: BibliographyExportOptions) -> bool:
    return options.url_policy == "include" or (
        options.url_policy == "omit_when_doi" and not record.doi
    )


def _export_ris(records: list[BibliographyRecord], options: BibliographyExportOptions) -> str:
    output: list[dict[str, Any]] = []
    for record in records:
        entry: dict[str, Any] = {
            "type_of_reference": REFERENCE_TYPE_TO_RIS.get(
                normalize_reference_type(record.reference_type) or "generic", "GEN"
            ),
        }
        if record.title and not _excluded(options, "title"):
            entry["title"] = convert_rich_text(record.title, source="html", target="text")
        optional = {
            "abstract": (
                convert_rich_text(record.abstract, source="html", target="text")
                if options.include_abstract and not _excluded(options, "abstract")
                else None
            ),
            "authors": (
                [person.display_name() for person in record.authors]
                if not _excluded(options, "author", "authors")
                else None
            ),
            "keywords": (
                list(record.keywords) if not _excluded(options, "keyword", "keywords") else None
            ),
            "year": record.publication_date if not _excluded(options, "year", "date") else None,
            "journal_name": (
                _export_journal(record, options)
                if not _excluded(options, "journal", "journaltitle")
                else None
            ),
            "doi": (
                record.doi
                if options.doi_policy == "include" and not _excluded(options, "doi")
                else None
            ),
            "urls": (
                list(record.urls)
                if record.urls
                and _include_url(record, options)
                and not _excluded(options, "url", "urls")
                else None
            ),
        }
        entry.update({key: value for key, value in optional.items() if value})
        output.append(entry)
    return rispy.dumps(output)


def _export_endnote(records: list[BibliographyRecord], options: BibliographyExportOptions) -> str:
    lines: list[str] = []
    for record in records:
        reference_type = REFERENCE_TYPE_TO_ENDNOTE.get(
            normalize_reference_type(record.reference_type) or "article", "Journal Article"
        )
        lines.append(f"%0 {reference_type}")
        if not _excluded(options, "author", "authors"):
            lines.extend(f"%A {person.display_name()}" for person in record.authors)
        if not _excluded(options, "editor", "editors"):
            lines.extend(f"%E {person.display_name()}" for person in record.editors)
        if record.title and not _excluded(options, "title"):
            lines.append(f"%T {convert_rich_text(record.title, source='html', target='text')}")
        journal = _export_journal(record, options)
        if journal and not _excluded(options, "journal", "journaltitle"):
            lines.append(f"%J {journal}")
        if record.publication_date and not _excluded(options, "year", "date"):
            lines.append(f"%D {record.publication_date}")
        if record.doi and options.doi_policy == "include" and not _excluded(options, "doi"):
            lines.append(f"%R {record.doi}")
        if not _excluded(options, "keyword", "keywords"):
            lines.extend(f"%K {keyword}" for keyword in record.keywords)
        if _include_url(record, options) and not _excluded(options, "url", "urls"):
            lines.extend(f"%U {url}" for url in record.urls)
        if options.include_abstract and record.abstract and not _excluded(options, "abstract"):
            lines.append(f"%X {convert_rich_text(record.abstract, source='html', target='text')}")
        lines.append("")
    return "\n".join(lines)


def export_bibliography_records(
    records: list[BibliographyRecord],
    file_format: str,
    *,
    options: BibliographyExportOptions | None = None,
) -> str:
    if file_format not in SUPPORTED_FORMATS:
        raise ValueError("format must be bibtex, biblatex, ris or endnote")
    options = (options or BibliographyExportOptions()).validated()
    if options.citation_key_formula.strip():
        validate_citation_key_formula(options.citation_key_formula)
        records = [
            replace(
                record,
                citation_key=evaluate_citation_key_formula(
                    options.citation_key_formula,
                    record,
                    force_ascii=options.citation_key_force_ascii,
                ),
            )
            if record.citation_key is None
            else record
            for record in records
        ]
    records = _sort_records(records, options.sort_by)
    if file_format == "endnote":
        return _export_endnote(records, options)
    if file_format == "ris":
        return _export_ris(records, options)
    entries: list[_V2Entry] = []
    used_keys: set[str] = set()
    for number, record in enumerate(records, start=1):
        base = record.citation_key or f"inquiro-{number}"
        key = base
        suffix_position = 1
        while unicodedata.normalize("NFKC", key).casefold() in used_keys:
            key = suffixed_citation_key(base, suffix_position)
            suffix_position += 1
        used_keys.add(unicodedata.normalize("NFKC", key).casefold())
        type_, fields = _entry_for_record(record, file_format, options)
        entries.append(
            _V2Entry(
                entry_type=type_,
                key=key,
                fields=[_V2Field(name, value) for name, value in fields.items()],
            )
        )
    return _write_bibtex_string(
        _V2Library(entries),
        unparse_stack=_BIBTEX_WRITE_STACK,
        bibtex_format=_BIBTEX_FORMAT,
    )
