from __future__ import annotations

import json

import pytest
from inquiro.bibliography import detect_bibliography_format, parse_bibliography_records


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("\ufeff \n@article{x,title={Research}}", "bibtex"),
        ("% Exported references\n@article{x,title={Research}}", "bibtex"),
        ("@string{journal = {Journal}}\n@article{x,title={Research}}", "bibtex"),
        ("TY  - JOUR\r\nTI  - Research\r\nER  -", "ris"),
        ('{"id":"x","type":"article-journal","title":"Research"}', "csl-json"),
        ('[{"type":"book","title":"Research"}]', "csl-json"),
        ('{"id":"song-1","type":"song","title":"A song"}', "csl-json"),
        ('{"id":"urn:uuid:test","type":"Book","title":"Research"}', "commonmeta"),
        ('[null, {"type":"Book","title":"Research"}]', "commonmeta"),
    ],
)
def test_detects_bibliography_syntax(content, expected):
    assert detect_bibliography_format(content) == expected


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        "{}",
        '"text"',
        '[{"type":"Book"}, {"type":"book"}]',
        '{"type":"Article"}',
        "Møller, A. P. Bumblebee preference for symmetrical flowers. PNAS, 1995.",
        "<xml><record><title>Research</title></record></xml>",
    ],
)
def test_does_not_guess_ambiguous_json_or_unsupported_formats(content):
    with pytest.raises(ValueError):
        detect_bibliography_format(content)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            '[{"type":"invalid"}, {"id":"urn:uuid:test","type":"Book","title":"Research"}]',
            "commonmeta",
        ),
        (
            '[{"type":"invalid"}, {"id":"x","type":"article-journal","title":"Research"}]',
            "csl-json",
        ),
        ('[{"type":"Article"}, {"type":"Book"}]', "commonmeta"),
        ('[{"type":"Article"}, {"type":"book"}]', "csl-json"),
        ('[{"type":[]}, {"type":42}, {"type":"Book"}]', "commonmeta"),
        ('{"container":{"title":"Journal"},"type":"Document"}', "commonmeta"),
    ],
)
def test_unknown_type_discriminators_do_not_vote(content, expected):
    assert detect_bibliography_format(content) == expected


def test_detection_preserves_malformed_typed_siblings_for_row_diagnostics():
    content = json.dumps([
        {"type": "invalid"},
        {"id": "urn:uuid:test", "type": "Book", "title": "Valid sibling"},
    ])
    records, errors = parse_bibliography_records(content, detect_bibliography_format(content))
    assert [record.work["title"] for record in records] == ["Valid sibling"]
    assert [error["row"] for error in errors] == [1]
    assert errors[0]["code"] == "invalid_record"


def test_detection_preserves_invalid_siblings_for_row_diagnostics():
    content = json.dumps([
        None,
        {"id": "urn:uuid:test", "type": "Book", "title": "Valid sibling"},
    ])
    records, errors = parse_bibliography_records(content, detect_bibliography_format(content))
    assert [record.work["title"] for record in records] == ["Valid sibling"]
    assert errors == [
        {
            "row": 1,
            "severity": "error",
            "code": "invalid_record",
            "message": "a bibliography record must be a JSON object",
        }
    ]
