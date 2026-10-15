"""Local interchange through commonmeta-py; format limitations are explicit."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import bibtexparser
from bibtexparser.bibdatabase import BibDatabase, as_text
from bibtexparser.bibtexexpression import BibtexExpression
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter
from commonmeta.schema_utils import schema_file_path

from inquiro._commonmeta_adapters import bibtex_writer_entry, ris_writer_record
from inquiro.bibliography.keys import evaluate_citation_key_formula, suffixed_citation_key
from inquiro.bibliography.options import BibliographyExportOptions
from inquiro.richtext import convert_rich_text
from inquiro.work import (
    _writer_work,
    contributor_name,
    contributor_suffix,
    read_work,
    validate_work,
    work_authors,
    work_doi,
    work_schema,
)

SUPPORTED_FORMATS = ("bibtex", "ris", "csl-json", "commonmeta")
BIBLIOGRAPHY_EXTENSIONS = {"bibtex": "bib", "ris": "ris", "csl-json": "json", "commonmeta": "json"}
BIBLIOGRAPHY_MEDIA_TYPES = {
    "bibtex": "application/x-bibtex",
    "ris": "application/x-research-info-systems",
    "csl-json": "application/vnd.citationstyles.csl+json",
    "commonmeta": "application/vnd.commonmeta+json",
}


@dataclass(frozen=True)
class ParsedRecord:
    work: dict
    citation_key: str | None = None
    row: int | None = None


@lru_cache(maxsize=1)
def _json_bibliography_types() -> dict[str, list[str]]:
    # Use the same bundled schemas as Work and CSL record validation. Detection
    # checks only the discriminator so malformed siblings retain row diagnostics.
    csl_schema = json.loads(Path(schema_file_path("csl")).read_text(encoding="utf-8"))
    return {
        "commonmeta": work_schema()["$defs"]["type"]["enum"],
        "csl-json": csl_schema["items"]["properties"]["type"]["enum"],
    }


def _json_format_votes(rows: list[Any]) -> set[str]:
    return {
        file_format
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("type"), str)
        for file_format, types in _json_bibliography_types().items()
        if row["type"] in types
    }


def detect_bibliography_format(content: str) -> str:
    """Recognize local interchange syntax without fetching metadata or guessing citations."""
    content = content.lstrip("\ufeff \t\r\n")
    if re.search(r"(?m)^[ \t]*@[A-Za-z]+\s*[{(]", content):
        return "bibtex"
    if re.search(r"(?m)^[ \t]*TY[ \t]+-", content):
        return "ris"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(
            "Could not detect bibliography format. Choose a format or provide BibTeX, RIS, "
            "CSL-JSON or Commonmeta; formatted reference text is not supported."
        ) from error
    rows = parsed if isinstance(parsed, list) else [parsed]
    # Examine every typed record so an invalid sibling cannot misclassify the whole
    # file; records without a recognized type stay available for per-row diagnostics.
    formats = _json_format_votes(rows)
    if not formats:
        raise ValueError(
            "Could not detect a JSON bibliography format. Choose CSL-JSON or Commonmeta "
            "explicitly; records without a recognized type are reported as diagnostics."
        )
    if len(formats) > 1:
        raise ValueError("JSON format is ambiguous; choose CSL-JSON or Commonmeta explicitly")
    return formats.pop()


def _bibtex_inputs(content: str) -> list[tuple[dict | None, str | None]]:
    database = bibtexparser.loads(
        content, parser=BibTexParser(interpolate_strings=False, ignore_nonstandard_types=False)
    )
    entries = iter(database.entries)
    inputs: list[tuple[dict | None, str | None]] = []

    def entry_found(_source, _location, _tokens):
        entry = next(entries)
        inputs.append((entry, entry.get("ID")))

    def unparsed_text(_source, _location, tokens):
        # UPSTREAM(bibtexparser 1.4.4): malformed declarations become implicit comments.
        # Use its documented grammar events to retain their place among real records;
        # explicit comments, macros, preambles and entry field values are separate events.
        inputs.extend((None, None) for _ in re.finditer(r"(?m)^[ \t]*@[A-Za-z]+\s*[{(]", tokens[0]))

    grammar = BibtexExpression()
    grammar.entry.add_parse_action(entry_found)
    grammar.implicit_comment.add_parse_action(unparsed_text)
    grammar.parse_file(StringIO(content.removeprefix("\ufeff")))
    return inputs


def parse_bibliography_records(
    content: str, file_format: str
) -> tuple[list[ParsedRecord], list[dict]]:
    if file_format not in SUPPORTED_FORMATS:
        raise ValueError("unsupported bibliography format")
    records, diagnostics = [], []
    inputs: list[tuple[Any, str | None]] = []
    if file_format == "bibtex":
        try:
            # Keep upstream macro expressions until each entry is processed;
            # an undefined macro must not prevent parsing its siblings.
            inputs = _bibtex_inputs(content)
        except (BibtexExpression.ParseException, ValueError, TypeError, KeyError) as error:
            return [], [
                {"severity": "error", "code": "invalid_bibliography", "message": str(error)}
            ]
    elif file_format == "ris":
        inputs = [
            (part.strip(), None) for part in re.split(r"(?m)(?=^TY\s+-)", content) if part.strip()
        ]
    else:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as error:
            return [], [{"severity": "error", "code": "invalid_json", "message": str(error)}]
        inputs = [(row, None) for row in (parsed if isinstance(parsed, list) else [parsed])]
    for row, (payload, key) in enumerate(inputs, 1):
        try:
            if file_format == "bibtex":
                if payload is None:
                    raise ValueError("Malformed BibTeX declaration was skipped by the parser")
                single = BibDatabase()
                single.entries = [{name: as_text(value) for name, value in payload.items()}]
                payload = bibtexparser.dumps(single)
            if file_format in {"commonmeta", "csl-json"} and not isinstance(payload, dict):
                raise ValueError("a bibliography record must be a JSON object")
            work = (
                payload
                if file_format == "commonmeta"
                else read_work(payload, "csl" if file_format == "csl-json" else file_format)
            )
            if file_format != "commonmeta" and (not work.get("id") or ":" not in work["id"]):
                work["id"] = f"urn:uuid:{uuid4()}"
            work = validate_work(work)
            records.append(ParsedRecord(work, key, row))
            if file_format in {"bibtex", "ris", "csl-json"}:
                diagnostics.append({
                    "row": row,
                    "severity": "warning",
                    "code": "format_limitations",
                    "message": "Commonmeta conversion supports a subset of this format; custom fields and unsupported source attributes are not retained. Use Commonmeta for lossless interchange.",
                })
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            diagnostics.append({
                "row": row,
                "severity": "error",
                "code": "invalid_record",
                "message": str(error),
            })
    if not inputs:
        diagnostics.append({
            "severity": "error",
            "code": "empty_bibliography",
            "message": "No bibliography records found",
        })
    return records, diagnostics


def export_bibliography_records(
    works: list[dict],
    file_format: str,
    *,
    options: BibliographyExportOptions | None = None,
    citation_keys: list[str | None] | None = None,
) -> str:
    if file_format not in SUPPORTED_FORMATS:
        raise ValueError("unsupported bibliography format")
    options = (options or BibliographyExportOptions()).validated(file_format=file_format)
    keys = citation_keys or [None] * len(works)
    if len(keys) != len(works):
        raise ValueError("citation key count does not match Work count")
    prepared = []
    used = set()
    for work, key in zip(works, keys, strict=True):
        work = validate_work(work)
        key = key or evaluate_citation_key_formula(
            options.citation_key_formula, work, force_ascii=options.citation_key_force_ascii
        )
        original, position = key, 0
        while unicodedata.normalize("NFKC", key).casefold() in used:
            position += 1
            key = suffixed_citation_key(original, position)
        used.add(unicodedata.normalize("NFKC", key).casefold())
        if file_format != "commonmeta" and not options.include_abstract:
            work.pop("description", None)
        prepared.append((work, key))
    if options.sort_by != "input":
        prepared.sort(key=lambda row: _export_sort_key(row, options.sort_by))
    if file_format == "commonmeta":
        return json.dumps([work for work, _ in prepared], ensure_ascii=False)
    if file_format == "csl-json":
        from inquiro.bibliography.engine import _work_to_csl_json

        return json.dumps(
            [_work_to_csl_json(_writer_work(work), options, item_id=key) for work, key in prepared],
            ensure_ascii=False,
        )
    # UPSTREAM(commonmeta-py 0.309): BibTeX/RIS writers attribute Editors as Authors.
    if any(
        any("Editor" in credit.get("roles", []) for credit in work.get("contributors", []))
        for work, _ in prepared
    ):
        raise ValueError(
            "commonmeta-py cannot preserve editor roles in BibTeX/RIS output; use Commonmeta or CSL-JSON"
        )
    snapshots = []
    for work, _ in prepared:
        snapshot = _writer_work(work)
        # UPSTREAM(commonmeta-py 0.309): these writers include all contributor roles.
        snapshot["contributors"] = work_authors(snapshot)
        for credit in snapshot["contributors"]:
            if not contributor_name(credit).strip():
                raise ValueError(
                    "Cannot export an author without a name as BibTeX/RIS; use Commonmeta"
                )
            if (person := credit.get("person")) and not person.get("family_name"):
                # UPSTREAM(commonmeta-py 0.309): BibTeX/RIS require a family slot even for a single
                # given name. Keep this fallback out of the CSL projection.
                person["family_name"] = person.get("name") or person["given_name"]
                person.pop("given_name", None)
            if suffix := contributor_suffix(credit):
                # UPSTREAM(commonmeta-py 0.309): no suffix field; a three-part name retains it in
                # the output-only snapshot used by its bibliography writers.
                credit["person"]["family_name"] += f", {suffix}"
        snapshots.append(snapshot)
    if file_format == "bibtex":
        # UPSTREAM(commonmeta-py 0.309): its batch writer sorts records. Map
        # each snapshot before serialization to preserve its Citation Key.
        database = BibDatabase()
        for snapshot, (_, key) in zip(snapshots, prepared, strict=True):
            doi = work_doi(snapshot)
            entry = bibtex_writer_entry(
                snapshot, doi=doi, encoding=options.encoding, preserve_case=options.preserve_case
            )
            if options.doi_policy == "omit":
                entry.pop("doi", None)
            if not options.includes_url(has_doi=bool(doi)):
                entry.pop("url", None)
            excluded = {field.casefold() for field in options.excluded_fields}
            entry = {
                field: value for field, value in entry.items() if field.casefold() not in excluded
            }
            entry["ID"] = key
            database.entries.append(entry)
        writer = BibTexWriter()
        writer.order_entries_by = ()
        return bibtexparser.dumps(database, writer=writer)
    return "\r\n\r\n".join(
        ris_writer_record(
            snapshot,
            doi=work_doi(snapshot),
            include_doi=options.doi_policy == "include",
            include_url=options.includes_url(has_doi=bool(work_doi(snapshot))),
        )
        for snapshot in snapshots
    )


def _export_sort_key(row: tuple[dict, str], sort_by: str) -> str:
    work, key = row
    if sort_by == "citation_key":
        return key.casefold()
    if sort_by == "year":
        return work.get("date_published", "")[:4]
    if sort_by == "author":
        authors = work_authors(work)
        if not authors:
            return ""
        first = authors[0]
        value = first.get("person", {}).get("family_name") if first["type"] == "Person" else None
        value = value or contributor_name(first)
    else:
        value = work.get("title", "")
    return convert_rich_text(value, source="html", target="text").casefold()
