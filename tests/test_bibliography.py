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
%@ 10.1234/endnote
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
    assert "%@ 10.1234/endnote" in output


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
    multiline_abstract = "First line of abstract.\nSecond line of abstract.\nThird line of abstract."
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
