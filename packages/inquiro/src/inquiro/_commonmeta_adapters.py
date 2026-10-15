"""Temporary input adapters and semantic guards for commonmeta-py 0.309.

Keep source conversion defects here, outside Providers and Library policy.
The support matrix and upstream reproducers live in docs/architecture/
item-metadata-json.md and docs/upstream/commonmeta-py-0.309/.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import uuid4

import bibtexparser
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bparser import BibTexParser
from bibtexparser.customization import page_double_hyphen, splitname
from citeproc.source.bibtex.bibtex import split_names
from commonmeta import Metadata
from commonmeta.author_utils import authors_as_string, get_authors
from commonmeta.base_utils import unique
from commonmeta.readers.bibtex_reader import read_bibtex
from commonmeta.readers.openalex_reader import read_openalex
from commonmeta.readers.ris_reader import read_ris
from commonmeta.schema_utils import json_schema_errors
from commonmeta.writers.bibtex_writer import write_bibtex_item

from inquiro.identifiers import canonical_doi, parse_doi
from inquiro.richtext import convert_rich_text


def reader_input(payload: Any, source: str) -> tuple[Any, str]:
    """Prepare upstream input and its reader, preserving facts before lossy conversion."""
    if source == "bibtex":
        return _bibtex_input(payload), "commonmeta"
    if source == "csl":
        return _csl_input(payload), source
    if source == "ris":
        return _ris_input(payload), "commonmeta"
    if source in {"crossref", "datacite", "openalex"}:
        return _native_provider_input(payload, source)
    return payload, source


def _doi_reader_uri(value: str) -> str:
    # UPSTREAM(commonmeta-py 0.309): readers lowercase non-ASCII DOI characters.
    # Encode the URI first so upstream case folding touches ASCII escapes only;
    # our comparison parser decodes the URI without folding non-ASCII letters.
    if not isinstance(value, str):
        raise TypeError("DOI must be a string")
    parsed = parse_doi(canonical_doi(value), "doi")
    if parsed is None:
        raise ValueError("record DOI is not a valid DOI")
    return f"https://doi.org/{quote(parsed.value, safe='/')}"


def _native_provider_input(payload: dict, source: str) -> tuple[dict, str]:
    if not isinstance(payload, dict):
        raise TypeError("provider record must be a JSON object")
    result = deepcopy(payload)
    key = "DOI" if source == "crossref" else "doi"
    # UPSTREAM(commonmeta-py 0.309): native readers emit raw URI paths and lowercase
    # non-ASCII DOI text. Escape before conversion, including literal percent signs.
    # URI-only lowercasing also keeps hexadecimal escapes identical for deduplication.
    if result.get(key):
        result[key] = _doi_reader_uri(result[key]).lower()
    if source != "openalex":
        return result, source
    identifiers = result.get("ids") or {}
    if not isinstance(identifiers, dict):
        raise TypeError("OpenAlex ids must be a JSON object")
    if identifiers.get("doi"):
        identifiers["doi"] = _doi_reader_uri(identifiers["doi"]).lower()
    # UPSTREAM(commonmeta-py 0.309): the OpenAlex reader uses resolved author
    # profile names instead of this work's byline, which can credit a different
    # name or append a duplicate during sync. Keep its ID/affiliation mapping.
    for credit in result.get("authorships") or []:
        raw_name = credit.get("raw_author_name")
        if isinstance(raw_name, str) and raw_name.strip():
            credit["author"] = {
                **(credit.get("author") or {}),
                "display_name": raw_name.strip(),
            }
    work = read_openalex(result)
    if doi := identifiers.get("doi"):
        # UPSTREAM(commonmeta-py 0.309): OpenAlex's secondary DOI normalizer drops
        # longer prefixes that the existing Inquiro parser accepts. Preserve that
        # confirmed identity after upstream field mapping, before serialization.
        rows = work.get("identifiers") or []
        if not any(row["identifier_type"] == "DOI" and row["identifier"] == doi for row in rows):
            work["identifiers"] = [*rows, {"identifier_type": "DOI", "identifier": doi}]
    return work, "commonmeta"


def _bibtex_input(payload: str) -> dict:
    database = bibtexparser.loads(payload, parser=BibTexParser(common_strings=True))
    if not database.entries:
        raise ValueError("No BibTeX record found")
    entry = database.entries[0]
    # UPSTREAM(commonmeta-py 0.309): Citation Keys can supply Work identity or be
    # classified as ROR/ORCID entities. Always use a temporary URI, including for
    # URI-shaped keys; bibliography parsing retains the local key separately.
    entry["ID"] = f"urn:uuid:{uuid4()}"
    if doi := entry.get("doi"):
        entry["doi"] = _doi_reader_uri(convert_rich_text(doi, source="latex", target="text"))
    single = BibDatabase()
    single.entries = [entry]
    # Keep upstream field/type mapping. Repair its lossy text/name conversion
    # from the still-grouped source before Metadata classifies and serializes it.
    result = read_bibtex(bibtexparser.dumps(single))
    if entry.get("doi"):
        # UPSTREAM(commonmeta-py 0.309): DOI normalization accepts only 4/5-digit
        # prefixes. Preserve the URI validated by Inquiro's existing DOI parser.
        result["id"] = entry["doi"]
    # UPSTREAM(commonmeta-py 0.309): convert_to_unicode strips TeX groups but
    # leaves formatting commands (e.g. \\textitgreat). Normalize original text
    # with the existing rich-text converter, also preserving inline math groups.
    for field, target in (("title", "title"), ("abstract", "description")):
        if entry.get(field):
            result[target] = convert_rich_text(entry[field], source="latex", target="html")
    if (container := result.get("container")) and (
        title := entry.get("journal") or entry.get("booktitle")
    ):
        container["title"] = convert_rich_text(title, source="latex", target="html")
    # UPSTREAM(commonmeta-py 0.309): protective name braces are removed before
    # splitting on `and`, and literal names containing commas become people.
    # Use the existing brace-aware splitter and upstream contributor utilities.
    contributors = []
    for field, role in (("author", "Author"), ("editor", "Editor")):
        for raw_name in split_names(entry.get(field, "")):
            raw_name = raw_name.strip()
            if not raw_name:
                continue
            try:
                parts = splitname(raw_name)
            except StopIteration as error:
                raise ValueError("BibTeX contributor has an incomplete escape") from error
            name = convert_rich_text(raw_name, source="latex", target="text")
            if raw_name.startswith("{") and parts["last"] == [raw_name]:
                contributors.extend(
                    get_authors([
                        {
                            "creatorName": {"type": "Organization", "#text": name},
                            "contributor_roles": [role],
                        }
                    ])
                )
            else:
                # UPSTREAM(commonmeta-py 0.309): _parse_names splits at only the first comma,
                # turning BibTeX's `von Last, Jr, First` into a corrupt given name. Parse the
                # original brace-aware credit before text conversion, using bibtexparser.
                source = {"name": name, "contributor_roles": [role]}
                suffix = None
                if "," in raw_name:
                    family = convert_rich_text(
                        " ".join(parts["von"] + parts["last"]), source="latex", target="text"
                    )
                    given = convert_rich_text(
                        " ".join(parts["first"]), source="latex", target="text"
                    )
                    suffix = convert_rich_text(" ".join(parts["jr"]), source="latex", target="text")
                    source.update(familyName=family, givenName=given)
                    name = " ".join(part for part in (given, family, suffix) if part)
                credits = get_authors([source])
                for credit in credits:
                    if suffix and credit["type"] == "Person":
                        # Commonmeta represents suffix facts in the full name; preserve them
                        # alongside structured parts for the existing citation projection.
                        credit["person"]["name"] = name
                contributors.extend(credits)
    if contributors:
        result["contributors"] = unique(contributors)
    return result


def _csl_input(payload: dict) -> dict:
    if error := json_schema_errors(payload, "csl"):
        raise ValueError(f"Invalid CSL-JSON record: {error}")
    # UPSTREAM(commonmeta-py 0.309): these reader mappings change the Work type.
    if payload.get("type") in {"article-magazine", "article-newspaper", "software"}:
        raise ValueError("this CSL type has an unreliable upstream conversion; use Commonmeta")
    result = deepcopy(payload)
    # UPSTREAM(commonmeta-py 0.309): the CSL reader prioritizes local record keys
    # over an explicit DOI and can mistake opaque keys for ROR identifiers.
    if doi := payload.get("DOI"):
        result["id"] = _doi_reader_uri(doi)
    elif not isinstance(payload["id"], str) or not urlsplit(payload["id"]).scheme:
        result["id"] = f"urn:uuid:{uuid4()}"

    issued = result.get("issued", {})
    endpoints = issued.get("date-parts", [])
    if len(endpoints) > 1:
        common = []
        # UPSTREAM(commonmeta-py 0.309): the reader keeps only the first endpoint,
        # inventing day precision. Retain only a shared year/month instead.
        for left, right in zip(endpoints[0][:2], endpoints[1][:2], strict=False):
            if left != right:
                break
            common.append(left)
        if common:
            issued["date-parts"] = [common]
        else:
            result.pop("issued", None)
    return result


def _ris_input(payload: str) -> dict:
    # UPSTREAM(commonmeta-py 0.309): its RIS tokenizer truncates hyphenated
    # values and cannot retain continuation lines or keywords/editor credits.
    lines = []
    title = None
    doi_uri = None
    for line in payload.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([A-Z0-9]{2})\s+-\s?(.*)", line)
        if match is None:
            raise ValueError("commonmeta-py cannot preserve RIS continuation lines; use Commonmeta")
        tag, value = match.groups()
        if "-" in value:
            raise ValueError(
                "commonmeta-py 0.309 truncates RIS values containing a hyphen; use Commonmeta or CSL-JSON"
            )
        if tag in {"KW", "A2", "ED"}:
            raise ValueError(
                "commonmeta-py cannot reliably preserve RIS keywords/editors; use Commonmeta or CSL-JSON"
            )
        if tag == "DO":
            value = _doi_reader_uri(value)
            doi_uri = value
        if tag in {"TI", "T1"}:
            # UPSTREAM(commonmeta-py 0.309): the reader recognizes T1 but ignores TI.
            if title is not None:
                if title != value:
                    raise ValueError("conflicting RIS TI/T1 titles cannot be converted losslessly")
                continue
            title = value
            tag = "T1"
        lines.append(f"{tag}  - {value}")
    result = read_ris("\n".join(lines))
    if doi_uri:
        # UPSTREAM(commonmeta-py 0.309): DOI normalization accepts only 4/5-digit
        # prefixes. Keep the validated URI before Commonmeta serialization.
        result["id"] = doi_uri
    return result


def check_csl_writer_input(work: dict) -> None:
    # UPSTREAM(commonmeta-py 0.309): versioned Software silently becomes a CSL book.
    if work["type"] == "Software" and work.get("version") is not None:
        raise ValueError(
            "commonmeta-py 0.309 converts versioned Software to a book in CSL; use Commonmeta"
        )


def bibtex_writer_entry(
    work: dict, *, doi: str | None = None, encoding: str = "unicode", preserve_case: bool = False
) -> dict:
    # UPSTREAM(commonmeta-py 0.309): retain its field mapping, but project text
    # before serialization. Its string writer emits HTML/raw TeX delimiters,
    # which can corrupt the entry before a later parse could repair it.
    entry = page_double_hyphen(write_bibtex_item(Metadata(work, via="commonmeta", no_network=True)))
    if doi:
        # UPSTREAM(commonmeta-py 0.309): doi_from_url returns escaped URI text,
        # not the raw DOI. Retain non-ASCII distinctions in the DOI field.
        entry["doi"] = doi
    for field, value in entry.items():
        if field in {"ID", "ENTRYTYPE", "author"}:
            continue
        entry[field] = convert_rich_text(
            value,
            source="html" if field in {"title", "abstract", "journal", "booktitle"} else "text",
            target="latex",
            latex_encoding="bibtex-latex" if encoding == "latex" else "bibtex",
        )
    if "author" in entry:
        # UPSTREAM(commonmeta-py 0.309): organization names require an inner
        # brace group; field delimiters alone do not protect commas or `and`.
        authors = []
        for credit in work["contributors"]:
            name = convert_rich_text(
                authors_as_string([credit]),
                source="text",
                target="latex",
                latex_encoding="bibtex-latex" if encoding == "latex" else "bibtex",
            )
            authors.append(f"{{{name}}}" if credit["type"] == "Organization" else name)
        entry["author"] = " and ".join(authors)
    if preserve_case and entry.get("title"):
        entry["title"] = "{" + entry["title"] + "}"
    return entry


def ris_writer_record(
    work: dict, *, doi: str | None = None, include_doi: bool = True, include_url: bool = True
) -> str:
    def plaintext_fields(values: dict, fields: tuple[str, ...]) -> dict:
        return {
            key: " ".join(convert_rich_text(value, source="html", target="text").split())
            if key in fields and isinstance(value, str)
            else value
            for key, value in values.items()
        }

    # UPSTREAM(commonmeta-py 0.309): RIS display values are emitted verbatim.
    # Project only display fields on a temporary snapshot; compact line breaks
    # so field values cannot become continuation lines or extra RIS records.
    snapshot = plaintext_fields(work, ("title", "description", "language"))
    for parent, fields in (
        ("container", ("title", "volume", "issue", "first_page", "last_page")),
        ("publisher", ("name",)),
    ):
        if parent in work:
            snapshot[parent] = plaintext_fields(work[parent], fields)
    if "contributors" in work:
        snapshot["contributors"] = []
        for credit in work["contributors"]:
            entity = credit["type"].lower()
            snapshot["contributors"].append({
                **credit,
                entity: plaintext_fields(credit[entity], ("name", "family_name", "given_name")),
            })
    if "subjects" in work:
        snapshot["subjects"] = [plaintext_fields(row, ("subject",)) for row in work["subjects"]]
    metadata = Metadata(snapshot, via="commonmeta", no_network=True)
    # RIS exposes its DOI through this per-call writer state. Presentation
    # policies never change the Work or synthesize a replacement Work identity.
    if not include_doi:
        metadata.id = None
    if not include_url:
        metadata.url = None
    output = metadata.write(to="ris")
    if output is None:
        raise ValueError("Commonmeta RIS conversion returned no record")
    text = output.decode("utf-8") if isinstance(output, bytes) else output
    if doi and include_doi:
        # UPSTREAM(commonmeta-py 0.309): restore the raw DOI separately from
        # the encoded resolver URI, replacing only this record's DO field.
        text, count = re.subn(r"(?m)^DO  - [^\r\n]*", lambda _: f"DO  - {doi}", text)
        if not count:
            # UPSTREAM(commonmeta-py 0.309): its DOI utility omits longer
            # prefixes supported by the existing Inquiro parser.
            text = re.sub(r"(?m)^ER  -", lambda _: f"DO  - {doi}\r\nER  -", text, count=1)
    return text
