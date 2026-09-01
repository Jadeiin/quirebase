import json

import pytest
import rispy
from bibtexparser import parse_string as parse_bibtex_string
from inquiro.bibliography import (
    BibliographyExportOptions,
    Contributor,
    export_bibliography_records,
    parse_bibliography_records,
    record_from_item,
)

from quirebase.models import Item, User


def _item_payload(record):
    import json as _json

    return {
        "title": record.title or None,
        "abstract": record.abstract,
        "authors": "; ".join(p.storage_name() for p in record.authors) or None,
        "editors": "; ".join(p.storage_name() for p in record.editors) or None,
        "keywords": "; ".join(record.keywords) or None,
        "publication_date": record.publication_date,
        "publication_title": record.publication_title or record.book_title,
        "volume": record.volume,
        "issue": record.issue,
        "pages": record.pages,
        "publisher": record.publisher,
        "place_published": record.location,
        "doi": record.doi,
        "reference_type": record.reference_type,
        "bibtex_id": record.citation_key,
        "bibtex_type": record.bibtex_type,
        "urls": "\n".join(record.urls) or None,
        "identifiers": _json.dumps(dict(record.identifiers), ensure_ascii=False)
        if record.identifiers
        else None,
        "custom_fields": _json.dumps(dict(record.custom_fields), ensure_ascii=False)
        if record.custom_fields
        else None,
    }


@pytest.mark.anyio
async def test_bibtex_parse_and_round_trip(async_db):
    db = async_db
    source = """@article{sample,
      title = {An Example Paper},
      author = {Doe, Jane and Smith, Alex},
      journal = {Testing Quarterly},
      year = {2025},
      doi = {10.1234/example}
    }"""
    typed, errors = parse_bibliography_records(source, "bibtex")
    records = [_item_payload(record) for record in typed]

    assert errors == []
    assert records[0]["authors"] == "Doe, Jane; Smith, Alex"
    user = User(username="bibtex", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(created_by=user.id, **records[0])
    output = export_bibliography_records([record_from_item(i) for i in [item]], "bibtex")

    exported = parse_bibtex_string(output).entries_dict["sample"]
    assert exported.fields_dict["title"].value == "An Example Paper"
    assert exported.fields_dict["doi"].value == "10.1234/example"


def test_bibtex_import_projects_literal_and_suffix_contributors_to_first_last():
    source = r"""@article{contributors,
      title = {Stable names},
      author = {{World Health Organization} and de la Cruz, Jr., Juan}
    }"""

    records, errors = parse_bibliography_records(source, "bibtex")
    stored = _item_payload(records[0])

    assert errors == []
    assert records[0].authors == (
        Contributor("World Health Organization"),
        Contributor("de la Cruz Jr.", "Juan"),
    )
    assert stored["authors"] == "{World Health Organization}; de la Cruz Jr., Juan"
    output = export_bibliography_records(records, "bibtex")
    round_trip, round_trip_errors = parse_bibliography_records(output, "bibtex")
    assert round_trip_errors == []
    assert round_trip[0].authors == records[0].authors


@pytest.mark.anyio
async def test_bibtex_export_can_protect_text_field_capitalization(async_db):
    db = async_db
    user = User(username="bibtex-case", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(
        title="An API for GraphQL and eBPF",
        abstract="Using CUDA with an LLM",
        authors="Doe, Jane; Smith, Alex",
        keywords="API; GraphQL",
        publication_title="Journal of eBPF Research",
        publisher="ACM Press",
        bibtex_id="case-protection",
        created_by=user.id,
    )

    ordinary = export_bibliography_records(
        [record_from_item(i) for i in [item]],
        "bibtex",
        options=BibliographyExportOptions(preserve_case=False),
    )
    protected = export_bibliography_records(
        [record_from_item(i) for i in [item]],
        "bibtex",
        options=BibliographyExportOptions(preserve_case=True),
    )

    assert "title = {An API for GraphQL and eBPF}" in ordinary
    assert "title = {{A}n {API} for {G}raph{QL} and e{BPF}}" in protected
    assert "abstract = {Using CUDA with an LLM}" in protected
    assert "keywords = {API; GraphQL}" in protected
    assert "journal = {Journal of eBPF Research}" in protected
    assert "publisher = {ACM Press}" in protected
    assert "author = {Doe, Jane and Smith, Alex}" in protected


@pytest.mark.anyio
async def test_duplicate_stored_citation_keys_are_disambiguated_only_for_export(async_db):
    db = async_db
    user = User(username="duplicate-export-keys", password_hash="unused")
    db.add(user)
    await db.flush()
    first = Item(title="First", bibtex_id="SharedKey", created_by=user.id)
    second = Item(title="Second", bibtex_id="sharedkey", created_by=user.id)
    db.add_all([first, second])
    await db.commit()

    output = export_bibliography_records([record_from_item(i) for i in [first, second]], "bibtex")
    entries = parse_bibtex_string(output).entries_dict

    assert first.bibtex_id == "SharedKey"
    assert second.bibtex_id == "sharedkey"
    assert list(entries) == ["SharedKey", "sharedkeya"]


@pytest.mark.anyio
async def test_bibtex_case_protection_does_not_add_repeated_outer_braces(async_db):
    db = async_db
    user = User(username="bibtex-braces", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(title="{Already Protected}", created_by=user.id)

    protected = export_bibliography_records(
        [record_from_item(i) for i in [item]],
        "bibtex",
        options=BibliographyExportOptions(preserve_case=True),
    )

    assert "title = {{Already Protected}}" in protected


@pytest.mark.anyio
async def test_bibtex_case_protection_leaves_latex_commands_intact(async_db):
    db = async_db
    user = User(username="bibtex-latex", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(title=r"Using \LaTeX with {CUDA}", created_by=user.id)

    protected = export_bibliography_records(
        [record_from_item(i) for i in [item]],
        "bibtex",
        options=BibliographyExportOptions(preserve_case=True),
    )

    assert r"title = {{U}sing \LaTeX with {CUDA}}" in protected


@pytest.mark.anyio
async def test_bibtex_export_can_include_identifiers_and_custom_fields(async_db):
    db = async_db
    user = User(username="bibtex-extras", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(
        title="Extra fields",
        identifiers=json.dumps({"openalex": "W123", "arxiv": "2401.00001"}),
        custom_fields=json.dumps({
            "dataset_id": "DS-42",
            "Study Quality": "High",
            "study_quality": "Medium",
            "foo:bar": "Baz",
            "reviewed": True,
        }),
        created_by=user.id,
    )

    output = export_bibliography_records(
        [record_from_item(item)],
        "bibtex",
        options=BibliographyExportOptions(
            include_identifiers=True,
            include_custom_fields=True,
        ),
    )

    assert "openalex = {W123}" in output
    assert "arxiv = {2401.00001}" in output
    assert "dataset_id = {DS-42}" in output
    assert "Study_Quality = {High}" in output
    assert "study_quality_2 = {Medium}" in output
    assert "foo_bar = {Baz}" in output
    assert "reviewed = {True}" in output
    typed, errors = parse_bibliography_records(output, "bibtex")
    records = [_item_payload(record) for record in typed]
    assert errors == []
    assert json.loads(records[0]["custom_fields"]) == {
        "dataset_id": "DS-42",
        "study_quality": "High",
        "study_quality_2": "Medium",
        "foo_bar": "Baz",
        "reviewed": "True",
    }


@pytest.mark.anyio
async def test_ris_parse_and_round_trip(async_db):
    db = async_db
    source = """TY  - JOUR
TI  - RIS Example
AU  - Example, Ada
KW  - search
PY  - 2024
ER  -
"""
    typed, errors = parse_bibliography_records(source, "ris")
    records = [_item_payload(record) for record in typed]

    assert errors == []
    user = User(username="ris", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(created_by=user.id, **records[0])
    output = export_bibliography_records([record_from_item(i) for i in [item]], "ris")

    exported = rispy.loads(output)[0]
    assert exported["title"] == "RIS Example"
    assert exported["authors"] == ["Example, Ada"]


@pytest.mark.anyio
async def test_endnote_parse_and_round_trip(async_db):
    db = async_db
    source = """%0 Journal Article
%A Doe, Jane
%A Smith, Alex
%T An EndNote Paper
%J EndNote Quarterly
%D 2025
%R 10.1234/endnote
%K search;testing
%X A full abstract.
"""
    typed, errors = parse_bibliography_records(source, "endnote")
    records = [_item_payload(record) for record in typed]

    assert errors == []
    assert records[0]["title"] == "An EndNote Paper"
    assert records[0]["authors"] == "Doe, Jane; Smith, Alex"
    assert records[0]["doi"] == "10.1234/endnote"
    assert records[0]["reference_type"] == "journal-article"

    user = User(username="endnote", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(created_by=user.id, **records[0])
    output = export_bibliography_records([record_from_item(i) for i in [item]], "endnote")

    assert output.splitlines()[0] == "%0 Journal Article"
    assert "%A Doe, Jane" in output
    assert "%A Smith, Alex" in output
    assert "%T An EndNote Paper" in output
    assert "%R 10.1234/endnote" in output


@pytest.mark.anyio
async def test_endnote_multiline_abstract_round_trip(async_db):
    db = async_db
    multiline_abstract = (
        "First line of abstract.\nSecond line of abstract.\nThird line of abstract."
    )
    source = f"""%0 Journal Article
%T Multiline Paper
%A Doe, Jane
%X {multiline_abstract}
"""
    typed, errors = parse_bibliography_records(source, "endnote")
    records = [_item_payload(record) for record in typed]
    assert errors == []
    assert records[0]["abstract"] == multiline_abstract

    user = User(username="multiline_user", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(created_by=user.id, **records[0])
    exported = export_bibliography_records([record_from_item(i) for i in [item]], "endnote")

    round_trip_typed, round_trip_errors = parse_bibliography_records(exported, "endnote")
    round_trip_records = [_item_payload(record) for record in round_trip_typed]
    assert round_trip_errors == []
    assert round_trip_records[0]["abstract"] == multiline_abstract
