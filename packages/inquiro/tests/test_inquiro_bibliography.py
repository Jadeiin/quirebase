import json

from inquiro.bibliography import parse_bibliography


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
    assert json.loads(records[0]["identifiers"]) == {
        "openalex": "W123",
        "arxiv": "2401.00001",
    }
    assert json.loads(records[0]["custom_fields"]) == {"dataset_id": "DS-42"}


def test_import_reports_each_missing_title():
    records, errors = parse_bibliography("TY  - JOUR\nAU  - Nobody\nER  -\n", "ris")

    assert len(records) == 1
    assert errors == [{"row": 1, "message": "Title is required"}]


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
