from __future__ import annotations

import httpx2
import pytest
from citeproc import types as csl_types
from inquiro.bibliography import (
    BibliographyRecord,
    export_bibliography_records,
    parse_bibliography_records,
    record_to_csl_json,
)
from inquiro.reference_types import ReferenceType, normalize_reference_type
from inquiro_provider_helpers import provider_runtime


def _source(file_format: str, entry_type: str, title: str = "Classification") -> str:
    if file_format in {"bibtex", "biblatex"}:
        return f"@{entry_type}{{record, title = {{{title}}}}}"
    if file_format == "ris":
        return f"TY  - {entry_type}\nTI  - {title}\nER  -\n"
    return f"%0 {entry_type}\n%T {title}\n"


@pytest.mark.parametrize(
    ("file_format", "entry_type", "expected"),
    [
        ("bibtex", "article", "article-journal"),
        ("bibtex", "proceedings", "book"),
        ("bibtex", "inbook", "chapter"),
        ("bibtex", "manual", "report"),
        ("bibtex", "phdthesis", "thesis"),
        ("bibtex", "mastersthesis", "thesis"),
        ("bibtex", "unpublished", "manuscript"),
        ("biblatex", "dataset", "dataset"),
        ("biblatex", "software", "software"),
        ("biblatex", "standard", "standard"),
        ("biblatex", "online", "webpage"),
        ("biblatex", "mvproceedings", "book"),
        ("ris", "MGZN", "article-magazine"),
        ("ris", "NEWS", "article-newspaper"),
        ("ris", "INPR", "article-journal"),
        ("ris", "STAND", "standard"),
        ("ris", "CONF", "book"),
        ("ris", "CPAPER", "paper-conference"),
        ("ris", "COMP", "software"),
        ("ris", "UNPB", "manuscript"),
        ("endnote", "Journal Article", "article-journal"),
        ("endnote", "Magazine Article", "article-magazine"),
        ("endnote", "Newspaper Article", "article-newspaper"),
        ("endnote", "Conference Proceedings", "book"),
        ("endnote", "Conference Paper", "paper-conference"),
        ("endnote", "Computer Program", "software"),
        ("endnote", "Generic", "document"),
    ],
)
def test_import_and_csl_projection_preserve_source_type_semantics(
    file_format, entry_type, expected
):
    records, diagnostics = parse_bibliography_records(_source(file_format, entry_type), file_format)

    assert diagnostics == []
    assert records[0].reference_type == expected
    assert record_to_csl_json(records[0])["type"] == expected


def test_general_article_is_distinct_from_journal_article_and_preprint():
    general = BibliographyRecord("general", ReferenceType.article, "A general article")
    journal = BibliographyRecord("journal", ReferenceType.article_journal, "A journal article")
    preprint = BibliographyRecord("preprint", ReferenceType.preprint, "A preprint")

    assert normalize_reference_type(csl_types.ARTICLE) == ReferenceType.article
    assert normalize_reference_type("article", source="bibtex") == ReferenceType.article_journal
    assert record_to_csl_json(general)["type"] == csl_types.ARTICLE
    assert record_to_csl_json(journal)["type"] == csl_types.ARTICLE_JOURNAL
    assert record_to_csl_json(preprint)["type"] == csl_types.ARTICLE


@pytest.mark.parametrize("file_format", ["bibtex", "biblatex", "ris", "endnote"])
def test_unknown_source_type_is_preserved_with_a_non_blocking_diagnostic(file_format):
    raw_type = "UNKNOWN"
    records, diagnostics = parse_bibliography_records(_source(file_format, raw_type), file_format)

    assert records[0].reference_type == ReferenceType.document
    assert record_to_csl_json(records[0])["type"] == "document"
    retained_type = raw_type.casefold() if file_format in {"bibtex", "biblatex"} else raw_type
    assert dict(records[0].custom_fields) == {
        "source_reference_type": retained_type,
        "source_reference_format": file_format,
    }
    assert len(diagnostics) == 1
    assert diagnostics[0]["severity"] == "warning"
    assert retained_type in diagnostics[0]["message"]


@pytest.mark.parametrize(
    ("reference_type", "file_format", "exported_type", "round_trip_type"),
    [
        ("paper-conference", "ris", "CPAPER", "paper-conference"),
        ("paper-conference", "endnote", "Conference Paper", "paper-conference"),
        ("article-magazine", "ris", "MGZN", "article-magazine"),
        ("article-newspaper", "endnote", "Newspaper Article", "article-newspaper"),
        ("software", "biblatex", "software", "software"),
        ("standard", "biblatex", "standard", "standard"),
        ("manuscript", "bibtex", "unpublished", "manuscript"),
        ("thesis", "bibtex", "misc", "document"),
        ("thesis", "biblatex", "thesis", "thesis"),
        ("dataset", "bibtex", "misc", "document"),
        ("article-magazine", "bibtex", "article", "article-journal"),
        ("document", "endnote", "Generic", "document"),
    ],
)
def test_directional_exports_and_deliberate_format_losses(
    reference_type, file_format, exported_type, round_trip_type
):
    output = export_bibliography_records(
        [BibliographyRecord("record", reference_type, "Classification")], file_format
    )
    type_line = {
        "bibtex": f"@{exported_type}{{",
        "biblatex": f"@{exported_type}{{",
        "ris": f"TY  - {exported_type}",
        "endnote": f"%0 {exported_type}",
    }[file_format]
    assert (
        type_line in output.splitlines() if file_format == "ris" else output.startswith(type_line)
    )
    records, diagnostics = parse_bibliography_records(output, file_format)
    assert diagnostics == []
    assert records[0].reference_type == round_trip_type


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("provider", "source_type", "expected"),
    [
        ("ieee", "Conferences", "paper-conference"),
        ("ieee", "Standards", "standard"),
        ("ieee", "Books", "chapter"),
        ("nasa_ads", "inproceedings", "paper-conference"),
        ("nasa_ads", "proceedings", "book"),
        ("nasa_ads", "phdthesis", "thesis"),
    ],
)
async def test_provider_lookup_uses_the_declared_content_type(provider, source_type, expected):
    import json

    from inquiro import ProviderConfig, ProviderRuntime
    from inquiro.transport import MockExchange, TransportResponse

    value = "1234567" if provider == "ieee" else "2025ApJ...123..456A"
    entry = {"title": "A classified record", "content_type": source_type, "doctype": source_type}
    payload = {"articles": [entry]} if provider == "ieee" else {"response": {"docs": [entry]}}
    async with ProviderRuntime.with_exchange(
        ProviderConfig(ieee_api_key="test", nasa_ads_token="test"),
        MockExchange(lambda _: TransportResponse(200, json.dumps(payload).encode())),
    ) as runtime:
        record = await runtime.lookup(value, provider=provider)

    assert record.reference_type == expected


@pytest.mark.anyio
async def test_datacite_general_type_survives_free_text_resource_description():
    payload = {
        "data": {
            "attributes": {
                "doi": "10.1000/dataset",
                "titles": [{"title": "A dataset"}],
                "types": {
                    "resourceType": "An annotated research dataset",
                    "resourceTypeGeneral": "Dataset",
                },
            }
        },
    }
    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=payload))
    ) as runtime:
        record = await runtime.lookup("10.1000/dataset", provider="datacite")
    assert record.reference_type == ReferenceType.dataset
