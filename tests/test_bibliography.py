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
