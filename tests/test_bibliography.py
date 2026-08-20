import json

import bibtexparser
import rispy

from quirebase.discovery import export_bibliography, parse_bibliography
from quirebase.models import Item, User


def test_bibtex_parse_and_round_trip(db):
    source = """@article{sample,
      title = {An Example Paper},
      author = {Doe, Jane and Smith, Alex},
      journal = {Testing Quarterly},
      year = {2025},
      doi = {10.1234/example}
    }"""
    records, errors = parse_bibliography(source, "bibtex")

    assert errors == []
    assert records[0]["authors"] == "Doe, Jane; Smith, Alex"
    user = User(username="bibtex", password_hash="unused")
    db.add(user)
    db.flush()
    item = Item(created_by=user.id, **records[0])
    output = export_bibliography([item], "bibtex")

    exported = bibtexparser.loads(output).entries[0]
    assert exported["title"] == "An Example Paper"
    assert exported["doi"] == "10.1234/example"


def test_bibtex_export_can_protect_text_field_capitalization(db):
    user = User(username="bibtex-case", password_hash="unused")
    db.add(user)
    db.flush()
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

    ordinary = export_bibliography([item], "bibtex", preserve_case=False)
    protected = export_bibliography([item], "bibtex", preserve_case=True)

    assert "title = {An API for GraphQL and eBPF}" in ordinary
    assert "title = {{A}n {API} for {G}raph{QL} and e{BPF}}" in protected
    assert "abstract = {Using CUDA with an LLM}" in protected
    assert "keywords = {API; GraphQL}" in protected
    assert "journal = {Journal of eBPF Research}" in protected
    assert "publisher = {ACM Press}" in protected
    assert "author = {Doe, Jane and Smith, Alex}" in protected


def test_bibtex_case_protection_does_not_add_repeated_outer_braces(db):
    user = User(username="bibtex-braces", password_hash="unused")
    db.add(user)
    db.flush()
    item = Item(title="{Already Protected}", created_by=user.id)

    protected = export_bibliography([item], "bibtex", preserve_case=True)

    assert "title = {{Already Protected}}" in protected


def test_bibtex_case_protection_leaves_latex_commands_intact(db):
    user = User(username="bibtex-latex", password_hash="unused")
    db.add(user)
    db.flush()
    item = Item(title=r"Using \LaTeX with {CUDA}", created_by=user.id)

    protected = export_bibliography([item], "bibtex", preserve_case=True)

    assert r"title = {{U}sing \LaTeX with {CUDA}}" in protected


def test_bibtex_export_can_include_identifiers_and_custom_fields(db):
    user = User(username="bibtex-extras", password_hash="unused")
    db.add(user)
    db.flush()
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

    output = export_bibliography(
        [item],
        "bibtex",
        include_identifiers=True,
        include_custom_fields=True,
    )

    assert "openalex = {W123}" in output
    assert "arxiv = {2401.00001}" in output
    assert "dataset_id = {DS-42}" in output
    assert "Study_Quality = {High}" in output
    assert "study_quality_2 = {Medium}" in output
    assert "foo_bar = {Baz}" in output
    assert "reviewed = {True}" in output
    records, errors = parse_bibliography(output, "bibtex")
    assert errors == []
    assert json.loads(records[0]["custom_fields"]) == {
        "dataset_id": "DS-42",
        "study_quality": "High",
        "study_quality_2": "Medium",
        "foo_bar": "Baz",
        "reviewed": "True",
    }


def test_bibtex_import_preserves_braced_case_identifiers_and_custom_fields():
    source = """@article{braced,
      title = {{An {API} for GraphQL}},
      author = {Doe, Jane},
      openalex = {W123},
      arxiv = {2401.00001},
      dataset_id = {DS-42}
    }"""

    records, errors = parse_bibliography(source, "bibtex")

    assert errors == []
    assert records[0]["title"] == "{An {API} for GraphQL}"
    assert records[0]["bibtex_id"] == "braced"
    assert json.loads(records[0]["identifiers"]) == {"openalex": "W123", "arxiv": "2401.00001"}
    assert json.loads(records[0]["custom_fields"]) == {"dataset_id": "DS-42"}


def test_ris_parse_and_round_trip(db):
    source = """TY  - JOUR
TI  - RIS Example
AU  - Example, Ada
KW  - search
PY  - 2024
ER  -
"""
    records, errors = parse_bibliography(source, "ris")

    assert errors == []
    user = User(username="ris", password_hash="unused")
    db.add(user)
    db.flush()
    item = Item(created_by=user.id, **records[0])
    output = export_bibliography([item], "ris")

    exported = rispy.loads(output)[0]
    assert exported["title"] == "RIS Example"
    assert exported["authors"] == ["Example, Ada"]


def test_import_reports_each_missing_title():
    records, errors = parse_bibliography("TY  - JOUR\nAU  - Nobody\nER  -\n", "ris")

    assert len(records) == 1
    assert errors == [{"row": 1, "message": "Title is required"}]


def test_endnote_parse_and_round_trip(db):
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
    records, errors = parse_bibliography(source, "endnote")

    assert errors == []
    assert records[0]["title"] == "An EndNote Paper"
    assert records[0]["authors"] == "Doe, Jane; Smith, Alex"
    assert records[0]["doi"] == "10.1234/endnote"
    assert records[0]["reference_type"] == "journal-article"

    user = User(username="endnote", password_hash="unused")
    db.add(user)
    db.flush()
    item = Item(created_by=user.id, **records[0])
    output = export_bibliography([item], "endnote")

    assert output.splitlines()[0] == "%0 Journal Article"
    assert "%A Doe, Jane" in output
    assert "%A Smith, Alex" in output
    assert "%T An EndNote Paper" in output
    assert "%R 10.1234/endnote" in output


def test_endnote_multiple_records_are_split():
    source = """%0 Journal Article
%T First Paper
%A One, Author

%0 Book
%T Second Book
%A Two, Author
"""
    records, errors = parse_bibliography(source, "endnote")

    assert errors == []
    assert len(records) == 2
    assert records[0]["title"] == "First Paper"
    assert records[1]["title"] == "Second Book"
    assert records[1]["reference_type"] == "book"


def test_endnote_multiline_abstract_round_trip(db):
    multiline_abstract = (
        "First line of abstract.\nSecond line of abstract.\nThird line of abstract."
    )
    source = f"""%0 Journal Article
%T Multiline Paper
%A Doe, Jane
%X {multiline_abstract}
"""
    records, errors = parse_bibliography(source, "endnote")
    assert errors == []
    assert records[0]["abstract"] == multiline_abstract

    user = User(username="multiline_user", password_hash="unused")
    db.add(user)
    db.flush()
    item = Item(created_by=user.id, **records[0])
    exported = export_bibliography([item], "endnote")

    round_trip_records, round_trip_errors = parse_bibliography(exported, "endnote")
    assert round_trip_errors == []
    assert round_trip_records[0]["abstract"] == multiline_abstract
