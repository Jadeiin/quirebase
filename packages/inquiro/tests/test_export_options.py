from __future__ import annotations

import json
import unicodedata
from copy import deepcopy

import bibtexparser
import pytest
from inquiro.bibliography import (
    BibliographyExportOptions,
    export_bibliography_records,
    parse_bibliography_records,
)
from inquiro.work import work_identifiers


def work(*, has_doi=True, **fields):
    return {
        "id": "https://doi.org/10.1000/options"
        if has_doi
        else "urn:uuid:00000000-0000-4000-8000-000000000001",
        "type": "JournalArticle",
        "title": "Research",
        "description": "Abstract",
        "url": "https://example.org/article",
        **fields,
    }


@pytest.mark.parametrize("file_format", ["bibtex", "csl-json"])
@pytest.mark.parametrize(
    "keys,expected",
    [
        (
            ["Café", "Cafe\u0301a", "cafe\u0301", "CAFÉ"],
            ["Café", "Cafe\u0301a", "cafe\u0301b", "CAFÉc"],
        ),
        (
            ["Key", "\uff2b\uff45\uff59a", "\uff4b\uff45\uff59", "KEY"],
            ["Key", "\uff2b\uff45\uff59a", "\uff4b\uff45\uff59b", "KEYc"],
        ),
    ],
)
def test_normalization_equivalent_citation_keys_receive_distinct_export_suffixes(
    file_format, keys, expected
):
    values = [work(title=f"Record {index}") for index in range(len(keys))]
    original = deepcopy(values)
    original_keys = keys[:]
    output = export_bibliography_records(values, file_format, citation_keys=keys)
    entries = bibtexparser.loads(output).entries if file_format == "bibtex" else json.loads(output)
    exported_keys = [entry["ID" if file_format == "bibtex" else "id"] for entry in entries]
    assert exported_keys == expected
    assert len({unicodedata.normalize("NFKC", key).casefold() for key in exported_keys}) == len(
        keys
    )
    assert values == original
    assert keys == original_keys


@pytest.mark.parametrize("file_format", ["bibtex", "ris", "csl-json"])
@pytest.mark.parametrize("has_doi", [False, True])
@pytest.mark.parametrize("doi_policy", ["include", "omit"])
@pytest.mark.parametrize("url_policy", ["include", "omit", "omit_when_doi"])
def test_identifier_display_policies_preserve_work_identity(
    file_format, has_doi, doi_policy, url_policy
):
    value = work(has_doi=has_doi)
    before = deepcopy(value)
    output = export_bibliography_records(
        [value],
        file_format,
        citation_keys=["Stable"],
        options=BibliographyExportOptions(doi_policy=doi_policy, url_policy=url_policy),
    )
    if file_format == "bibtex":
        entry = bibtexparser.loads(output).entries[0]
        doi, url = entry.get("doi"), entry.get("url")
        assert entry["ID"] == "Stable"
    elif file_format == "csl-json":
        entry = json.loads(output)[0]
        doi, url = entry.get("DOI"), entry.get("URL")
        assert entry["id"] == "Stable"
    else:
        fields = dict(line.split("  - ", 1) for line in output.splitlines())
        doi, url = fields.get("DO"), fields.get("UR")
        assert fields["TY"] == "JOUR" and "ER" in fields
    assert bool(doi) == (has_doi and doi_policy == "include")
    assert bool(url) == (url_policy == "include" or (url_policy == "omit_when_doi" and not has_doi))
    assert value == before


@pytest.mark.parametrize("encoding", ["unicode", "latex"])
def test_bibtex_character_representation_retains_safe_tex_and_case_protection(encoding):
    value = work(
        title="<i>DNA</i> café {unclosed & 50% $H_2O$",
        contributors=[
            {
                "type": "Organization",
                "organization": {"name": "R&D café Council"},
                "roles": ["Author"],
            }
        ],
    )
    before = deepcopy(value)
    output = export_bibliography_records(
        [value],
        "bibtex",
        citation_keys=["Safe"],
        options=BibliographyExportOptions(encoding=encoding, preserve_case=True),
    )
    entries = bibtexparser.loads(output).entries
    assert len(entries) == 1
    entry = entries[0]
    assert entry["title"].startswith("{") and entry["title"].endswith("}")
    assert r"\textit{DNA}" in entry["title"] and r"\textbraceleft{}" in entry["title"]
    assert r"\&" in entry["title"] and r"\%" in entry["title"]
    assert "$H_2O$" in entry["title"]
    assert entry["author"].startswith("{") and entry["author"].endswith("}")
    assert ("café" in entry["title"]) == (encoding == "unicode")
    assert value == before


@pytest.mark.parametrize("encoding", ["unicode", "latex"])
def test_encoding_does_not_change_non_ascii_doi_identity(encoding):
    value = work(id="https://doi.org/10.1000/%C3%84BC")
    output = export_bibliography_records(
        [value], "bibtex", options=BibliographyExportOptions(encoding=encoding)
    )
    records, errors = parse_bibliography_records(output, "bibtex")
    assert len(records) == 1 and not any(row["severity"] == "error" for row in errors)
    assert work_identifiers(records[0].work) == work_identifiers(value)


@pytest.mark.parametrize("file_format", ["bibtex", "csl-json"])
def test_native_field_exclusions_keep_required_fields(file_format):
    value = work()
    before = deepcopy(value)
    output = export_bibliography_records(
        [value],
        file_format,
        citation_keys=["Stable"],
        options=BibliographyExportOptions(excluded_fields=("ABSTRACT", "url")),
    )
    entry = (
        bibtexparser.loads(output).entries[0] if file_format == "bibtex" else json.loads(output)[0]
    )
    assert not {field.casefold() for field in entry}.intersection({"abstract", "url"})
    assert entry["ID" if file_format == "bibtex" else "id"] == "Stable"
    assert entry["ENTRYTYPE" if file_format == "bibtex" else "type"]
    assert value == before


@pytest.mark.parametrize(
    "file_format,field",
    [
        ("bibtex", "ID"),
        ("bibtex", "ENTRYTYPE"),
        ("csl-json", "id"),
        ("csl-json", "type"),
        ("ris", "AB"),
        ("commonmeta", "description"),
    ],
)
def test_unsupported_exclusions_are_explicit_errors(file_format, field):
    with pytest.raises(ValueError):
        export_bibliography_records(
            [work()], file_format, options=BibliographyExportOptions(excluded_fields=(field,))
        )


@pytest.mark.parametrize("file_format", ["bibtex", "ris", "csl-json", "commonmeta"])
def test_author_sorting_keeps_citation_keys_attached(file_format):
    values = [
        work(
            title="Zebra",
            contributors=[
                {
                    "type": "Person",
                    "person": {"family_name": "Zebra", "given_name": "Ada", "name": "A. Zebra"},
                    "roles": ["Author"],
                }
            ],
        ),
        work(
            title="Apple",
            contributors=[
                {
                    "type": "Organization",
                    "organization": {"name": "Apple Council"},
                    "roles": ["Author"],
                }
            ],
        ),
    ]
    output = export_bibliography_records(
        values,
        file_format,
        citation_keys=["zebra", "apple"],
        options=BibliographyExportOptions(sort_by="author"),
    )
    if file_format == "bibtex":
        assert [(entry["title"], entry["ID"]) for entry in bibtexparser.loads(output).entries] == [
            ("Apple", "apple"),
            ("Zebra", "zebra"),
        ]
    elif file_format == "ris":
        assert output.index("T1  - Apple") < output.index("T1  - Zebra")
    else:
        entries = json.loads(output)
        assert [entry["title"] for entry in entries] == ["Apple", "Zebra"]
        if file_format == "csl-json":
            assert [entry["id"] for entry in entries] == ["apple", "zebra"]


def test_commonmeta_remains_complete_despite_presentation_preferences():
    value = work()
    output = export_bibliography_records(
        [value],
        "commonmeta",
        options=BibliographyExportOptions(
            include_abstract=False,
            doi_policy="omit",
            url_policy="omit",
            encoding="latex",
            preserve_case=True,
        ),
    )
    assert json.loads(output) == [value]


@pytest.mark.parametrize(
    "fields",
    [
        {"encoding": "invalid"},
        {"doi_policy": "invalid"},
        {"url_policy": "invalid"},
        {"excluded_fields": ("bad field",)},
    ],
)
def test_invalid_export_preferences_fail_before_writing(fields):
    with pytest.raises(ValueError):
        export_bibliography_records([work()], "bibtex", options=BibliographyExportOptions(**fields))
