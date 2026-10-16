from __future__ import annotations

import json
from copy import deepcopy
from urllib.parse import quote
from uuid import uuid4

import pytest
from inquiro import Work
from inquiro.bibliography import (
    builtin_style_xml,
    export_bibliography_records,
    parse_bibliography_records,
    render_citation,
    work_to_csl_json,
)
from inquiro.work import work_identifiers
from pydantic import ValidationError


def local_work(**fields):
    return {"id": f"urn:uuid:{uuid4()}", "type": "Preprint", "title": "Research", **fields}


@pytest.mark.parametrize("file_format", ["bibtex", "ris", "csl-json", "commonmeta"])
def test_export_validates_each_work_once_and_preserves_input(file_format, monkeypatch):
    import inquiro.work as work_module

    validator = work_module._validator()
    validations = 0

    class CountingValidator:
        def iter_errors(self, value):
            nonlocal validations
            validations += 1
            return validator.iter_errors(value)

    monkeypatch.setattr(work_module, "_validator", CountingValidator)
    values = [local_work(title="First"), local_work(title="Second")]
    original = deepcopy(values)
    export_bibliography_records(values, file_format)
    assert validations == len(values)
    assert values == original
    with pytest.raises(ValueError):
        export_bibliography_records([local_work(title=123)], file_format)


@pytest.mark.parametrize(
    "changed",
    [
        {"type": "invalid"},
        {"id": "not a URI"},
        {"title": 123},
        {"custom_fields": {}},
        {"contributors": [{"type": "Person"}]},
        {"subjects": ["keyword"]},
        {"date_published": "yesterday"},
        {"identifiers": [{"identifier_type": "DOI"}]},
    ],
)
def test_generated_work_rejects_invalid_contract(changed):
    with pytest.raises(ValidationError):
        Work.model_validate(local_work(**changed))


def test_generated_work_preserves_all_standard_fields():
    value = local_work(
        contributors=[
            {"type": "Organization", "organization": {"name": "Council"}, "roles": ["Author"]}
        ],
        container={"identifiers": [{"identifier_type": "ISBN", "identifier": "9780131103627"}]},
        relations=[{"id": "https://doi.org/10.1234/related", "type": "IsSupplementTo"}],
        subjects=[{"subject": "Graph; theory"}],
        language="en",
    )
    assert Work.model_validate(value).model_dump(mode="json", exclude_none=True) == value


def test_supported_identifier_comparison_preserves_multiple_values_and_ascii_doi_rule():
    value = local_work(
        id="https://doi.org/10.1234/ÄBC",
        identifiers=[
            {"identifier_type": "DOI", "identifier": "doi:10.1234/Äbc"},
            {"identifier_type": "DOI", "identifier": "10.1234/äbc"},
            {"identifier_type": "ISBN", "identifier": "ISBN: 978-0-13-110362-7"},
            {"identifier_type": "arXiv", "identifier": "https://arxiv.org/abs/2401.00001"},
        ],
    )
    assert work_identifiers(value) == {
        ("doi", "10.1234/Äbc"),
        ("doi", "10.1234/äbc"),
        ("isbn", "9780131103627"),
        ("arxiv", "2401.00001"),
    }


@pytest.mark.parametrize(
    "kind,identifier,expected",
    [
        ("PMID", "https://pubmed.ncbi.nlm.nih.gov/42", ("pmid", "42")),
        ("PMID", "https://www.ncbi.nlm.nih.gov/pubmed/42/", ("pmid", "42")),
        ("PMCID", "https://pmc.ncbi.nlm.nih.gov/articles/PMC42/", ("pmcid", "PMC42")),
        ("PMCID", "http://www.ncbi.nlm.nih.gov/pmc/articles/PMC42/", ("pmcid", "PMC42")),
    ],
)
def test_pubmed_resolver_identifiers_compare_without_rewriting_the_work(kind, identifier, expected):
    value = local_work(identifiers=[{"identifier_type": kind, "identifier": identifier}])
    original = deepcopy(value)
    assert work_identifiers(value) == {expected}
    assert value == original


@pytest.mark.parametrize(
    "kind,identifier",
    [
        ("PMID", "https://pmc.ncbi.nlm.nih.gov/articles/PMC42/"),
        ("PMCID", "https://www.ncbi.nlm.nih.gov/pubmed/42/"),
        ("PMID", "https://pubmed.ncbi.nlm.nih.gov/42/other"),
        ("PMCID", "https://www.ncbi.nlm.nih.gov/books/42/"),
        ("PMID", "https://pubmed.ncbi.nlm.nih.gov.evil.test/42/"),
    ],
)
def test_pubmed_identifier_urls_do_not_match_other_resources(kind, identifier):
    assert (
        work_identifiers(
            local_work(identifiers=[{"identifier_type": kind, "identifier": identifier}])
        )
        == set()
    )


@pytest.mark.parametrize("kind", ["PMID", "PMCID"])
@pytest.mark.parametrize(
    "identifier", ["https://[bad", "https://[not-ipv6]/42", "https://host\uff0f42"]
)
def test_malformed_pubmed_urls_are_ignored_without_losing_usable_identifiers(kind, identifier):
    value = local_work(
        identifiers=[
            {"identifier_type": kind, "identifier": identifier},
            {"identifier_type": "DOI", "identifier": "10.1234/usable"},
        ]
    )
    original = deepcopy(value)
    validated = Work.model_validate(value).model_dump(mode="json", exclude_none=True)
    assert work_identifiers(validated) == {("doi", "10.1234/usable")}
    assert value == original


@pytest.mark.parametrize("doi", ["10.1234/Über", "10.1234/A%3c", "10.123456/Über"])
def test_openalex_secondary_doi_uri_preserves_identity_without_mutating_source(doi):
    from inquiro.identifiers import canonical_doi
    from inquiro.work import read_work, validate_work

    payload = {
        "id": "https://openalex.org/W123",
        "display_name": "Example",
        "ids": {"doi": f"https://doi.org/{quote(doi, safe='/')}"},
    }
    before = deepcopy(payload)
    value = validate_work(read_work(payload, "openalex"))
    assert ("doi", canonical_doi(doi)) in work_identifiers(value)
    assert payload == before


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("https://doi.org/10.1234/%C3%9Cber", "10.1234/Über"),
        ("https://doi.org/10.1234/%c3%bcber", "10.1234/über"),
        ("https://doi.org/10.1234/100%253c", "10.1234/100%3c"),
        ("10.1234/100%3c", "10.1234/100%3c"),
        ("doi:10.1234/100%3c", "10.1234/100%3c"),
        ("https://doi.org/10.1234/%ff", "10.1234/%ff"),
        ("https://doi.org/10.1234/%fe", "10.1234/%fe"),
    ],
)
def test_doi_comparison_decodes_resolver_uris_once_and_preserves_raw_identifier_text(
    identifier, expected
):
    assert work_identifiers(
        local_work(identifiers=[{"identifier_type": "DOI", "identifier": identifier}])
    ) == {("doi", expected)}


@pytest.mark.parametrize("file_format", ["bibtex", "ris", "csl-json"])
@pytest.mark.parametrize(
    "doi", ["10.1234/Über", "10.1234/über", "10.1234/100%3c", "10.123456/Über"]
)
@pytest.mark.parametrize("primary", [False, True])
def test_export_preserves_raw_doi_and_reimport_comparison_identity(file_format, doi, primary):
    import bibtexparser

    value = local_work(
        type="JournalArticle",
        **({"id": f"https://doi.org/{quote(doi, safe='/')}"} if primary else {}),
        identifiers=[{"identifier_type": "DOI", "identifier": doi}],
    )
    original = deepcopy(value)
    output = export_bibliography_records([value], file_format, citation_keys=["unicode"])
    if file_format == "bibtex":
        from inquiro.richtext import convert_rich_text

        exported_doi = convert_rich_text(
            bibtexparser.loads(output).entries[0]["doi"], source="latex", target="text"
        )
    elif file_format == "ris":
        exported_doi = next(line[6:] for line in output.splitlines() if line.startswith("DO  - "))
    else:
        exported_doi = json.loads(output)[0]["DOI"]
    assert exported_doi == doi
    records, diagnostics = parse_bibliography_records(output, file_format)
    assert len(records) == 1, diagnostics
    assert work_identifiers(records[0].work) == work_identifiers(value)
    assert value == original


@pytest.mark.parametrize("file_format", ["bibtex", "ris", "csl-json"])
def test_batch_doi_exports_preserve_each_records_unicode_identity(file_format):
    values = [
        local_work(
            type="JournalArticle",
            title=title,
            identifiers=[{"identifier_type": "DOI", "identifier": doi}],
        )
        for title, doi in (("First", "10.1234/Über"), ("Second", "10.1234/über"))
    ]
    output = export_bibliography_records(values, file_format, citation_keys=["first", "second"])
    records, diagnostics = parse_bibliography_records(output, file_format)
    assert len(records) == 2, diagnostics
    assert {record.work["title"]: work_identifiers(record.work) for record in records} == {
        value["title"]: work_identifiers(value) for value in values
    }


@pytest.mark.parametrize(
    "file_format, content",
    [
        (
            "bibtex",
            "@article{first,title={First},doi={10.1234/first}}\n@book{second,title={Second},doi={10.1234/second}}",
        ),
        (
            "ris",
            "TY  - JOUR\nT1  - First\nDO  - 10.1234/first\nER  - \nTY  - BOOK\nT1  - Second\nDO  - 10.1234/second\nER  - ",
        ),
        (
            "csl-json",
            json.dumps([
                {
                    "id": "https://doi.org/10.1234/first",
                    "type": "article-journal",
                    "title": "First",
                },
                {"id": "https://doi.org/10.1234/second", "type": "book", "title": "Second"},
            ]),
        ),
    ],
)
def test_batch_interchange_is_offline_and_preserves_record_count(file_format, content, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("local conversion attempted network I/O")

    monkeypatch.setattr("requests.sessions.Session.request", no_network)
    records, diagnostics = parse_bibliography_records(content, file_format)
    assert len(records) == 2
    assert not any(row["severity"] == "error" for row in diagnostics)
    assert [row.work["title"] for row in records] == ["First", "Second"]
    output = export_bibliography_records(
        [row.work for row in records], file_format, citation_keys=["first", "second"]
    )
    reparsed, _ = parse_bibliography_records(output, file_format)
    assert len(reparsed) == 2
    if file_format == "bibtex":
        assert {row.citation_key for row in reparsed} == {"first", "second"}


def test_commonmeta_export_keeps_duplicate_bibliographic_ids():
    value = local_work(id="https://doi.org/10.1234/shared")
    exported = export_bibliography_records([value, value], "commonmeta")
    records, errors = parse_bibliography_records(exported, "commonmeta")
    assert len(records) == 2 and errors == []
    assert records[0].work == records[1].work == value


@pytest.mark.parametrize(
    "key",
    [
        "https://doi.org/10.1234/local-key",
        "https://pubmed.ncbi.nlm.nih.gov/42",
        "https://example.org/local-key",
    ],
)
@pytest.mark.parametrize(
    "identity",
    [None, "https://doi.org/10.1234/source", "https://example.org/source"],
)
def test_bibtex_uri_shaped_citation_keys_do_not_supply_work_identity(key, identity):
    value = local_work(**({"id": identity, "url": identity} if identity else {}))
    original = deepcopy(value)
    exported = export_bibliography_records([value], "bibtex", citation_keys=[key])
    records, diagnostics = parse_bibliography_records(exported, "bibtex")
    assert len(records) == 1, diagnostics
    restored = records[0]
    assert restored.citation_key == key
    assert work_identifiers(restored.work) == work_identifiers(value)
    if identity:
        assert restored.work["id"] == identity
    else:
        assert restored.work["id"].startswith("urn:uuid:")
    projected = work_to_csl_json(restored.work)
    assert projected.get("DOI") == (
        "10.1234/source" if identity and "doi.org" in identity else None
    )
    assert value == original


@pytest.mark.parametrize("source", ["article-magazine", "article-newspaper", "software"])
def test_unreliable_csl_types_are_explicit_errors(source):
    records, errors = parse_bibliography_records(
        json.dumps({"id": "https://doi.org/10.1234/test", "type": source, "title": "Test"}),
        "csl-json",
    )
    assert records == [] and errors[0]["severity"] == "error"


def test_ris_keywords_are_diagnosed_instead_of_lost():
    records, errors = parse_bibliography_records(
        "TY  - JOUR\nT1  - Test\nKW  - keyword\nER  - ", "ris"
    )
    assert records == [] and errors[0]["severity"] == "error"


def test_preprint_csl_and_custom_style_html_text_rendering():
    value = local_work(
        contributors=[
            {
                "type": "Person",
                "person": {"family_name": "Smith", "given_name": "Jane"},
                "roles": ["Author"],
            }
        ],
        date_published="2024",
    )
    assert work_to_csl_json(value)["type"] == "article"
    xml = builtin_style_xml("apa")
    assert xml
    plain = render_citation(value, xml)
    html = render_citation(value, xml, output_format="html")
    assert "Smith" in plain and "2024" in plain
    assert "Research" in html and "<i>" in html


def test_lookup_aliases_and_malformed_values_do_not_become_identity_matches():
    from inquiro.work import work_identifiers

    assert (
        work_identifiers({
            "id": "urn:uuid:00000000-0000-4000-8000-000000000001",
            "type": "Other",
            "identifiers": [
                {"identifier_type": "DOI", "identifier": "not-a-doi"},
                {"identifier_type": "OpenAlex", "identifier": "10.1234/lookup-alias"},
            ],
        })
        == set()
    )


@pytest.mark.parametrize(
    ("person", "expected"),
    [
        ({"given_name": "Ada", "family_name": "Lovelace"}, "Ada Lovelace"),
        ({"name": "", "given_name": "Xiang", "family_name": "Yu"}, "Xiang Yu"),
        ({"name": None, "given_name": "Juan", "family_name": "de la Cruz"}, "Juan de la Cruz"),
        ({"name": "Wang Wei", "given_name": "Wei", "family_name": "Wang"}, "Wang Wei"),
        ({"given_name": "Ada"}, "Ada"),
        ({"family_name": "Lovelace"}, "Lovelace"),
        ({}, ""),
    ],
)
def test_contributor_display_name_uses_reading_order_without_a_full_name(person, expected):
    from inquiro.work import contributor_name

    assert contributor_name({"type": "Person", "person": person}) == expected


def test_contributor_type_selects_active_names_keys_and_writer_credits_without_losing_work():
    from inquiro.bibliography.keys import evaluate_citation_key_formula
    from inquiro.work import contributor_name, writer_work

    credit = {
        "type": "Organization",
        "person": {"name": "Ada Researcher", "family_name": "Researcher", "given_name": "Ada"},
        "organization": {"name": "Research Council"},
        "roles": ["Author"],
    }
    value = local_work(contributors=[credit])
    assert contributor_name(credit) == "Research Council"
    assert evaluate_citation_key_formula("auth", value) == "ResearchCouncil"
    assert work_to_csl_json(value)["author"] == [{"literal": "Research Council"}]
    assert "person" not in writer_work(value)["contributors"][0]
    assert Work.model_validate(value).model_dump(mode="json", exclude_none=True) == value
    assert json.loads(export_bibliography_records([value], "commonmeta")) == [value]
    credit["type"] = "Person"
    assert contributor_name(credit) == "Ada Researcher"
    assert work_to_csl_json(value)["author"] == [{"family": "Researcher", "given": "Ada"}]
    assert "organization" not in writer_work(value)["contributors"][0]
    assert value["contributors"][0]["organization"] == {"name": "Research Council"}


@pytest.mark.parametrize("sort_by", ["input", "title", "citation_key", "year"])
@pytest.mark.parametrize("shared_id", [False, True])
def test_bibtex_keys_stay_with_their_records_across_writer_sorting(sort_by, shared_id):
    import bibtexparser
    from inquiro.bibliography import BibliographyExportOptions

    works = [
        local_work(id="https://doi.org/10.1000/zebra", title="Zebra", date_published="2025"),
        local_work(
            id="https://doi.org/10.1000/zebra" if shared_id else "https://doi.org/10.1000/apple",
            title="Apple",
            date_published="2024",
        ),
    ]
    output = export_bibliography_records(
        works,
        "bibtex",
        citation_keys=["first", "second"],
        options=BibliographyExportOptions(sort_by=sort_by),
    )
    entries = bibtexparser.loads(output).entries
    assert len(entries) == 2
    assert {entry["ID"]: entry["title"] for entry in entries} == {
        "first": "Zebra",
        "second": "Apple",
    }
    assert [entry["ID"] for entry in entries] == (
        ["second", "first"] if sort_by in {"title", "year"} else ["first", "second"]
    )


@pytest.mark.parametrize("file_format", ["bibtex", "ris"])
def test_bibliography_exports_only_the_active_author_entity(file_format):
    value = local_work(
        contributors=[
            {
                "type": "Organization",
                "organization": {"name": "Research Council"},
                "person": {"name": "Old Person", "family_name": "Person", "given_name": "Old"},
                "roles": ["Author"],
            }
        ]
    )
    output = export_bibliography_records([value], file_format)
    assert "Research Council" in output
    assert "Person" not in output
    assert value["contributors"][0]["person"]["family_name"] == "Person"


@pytest.mark.parametrize("file_format", ["csl-json", "bibtex", "ris"])
@pytest.mark.parametrize("name", ["Ada Lovelace", "Prince", "John Smith Jr."])
def test_name_only_people_survive_writer_projections(file_format, name):
    value = local_work(
        contributors=[{"type": "Person", "person": {"name": name}, "roles": ["Author"]}]
    )
    original = deepcopy(value)
    output = export_bibliography_records([value], file_format)
    if file_format == "csl-json":
        author = json.loads(output)[0]["author"][0]
        assert author.get("family")
        assert name.split()[0] in " ".join(author.values())
        if name == "John Smith Jr.":
            assert author["suffix"] == "Jr."
    else:
        assert name.split()[0] in output
        assert (
            "Lovelace" if name == "Ada Lovelace" else "Smith" if "Smith" in name else "Prince"
        ) in output
        if name == "John Smith Jr.":
            assert "Jr." in output
    assert value == original
    assert json.loads(export_bibliography_records([value], "commonmeta")) == [original]


@pytest.mark.parametrize("file_format", ["csl-json", "bibtex", "ris"])
def test_given_name_only_people_survive_writer_projections(file_format):
    value = local_work(
        contributors=[{"type": "Person", "person": {"given_name": "Ada"}, "roles": ["Author"]}]
    )
    original = deepcopy(value)
    output = export_bibliography_records([value], file_format)
    if file_format == "csl-json":
        assert json.loads(output)[0]["author"] == [{"given": "Ada"}]
    else:
        assert "Ada" in output
    assert value == original


@pytest.mark.parametrize("file_format", ["bibtex", "ris"])
@pytest.mark.parametrize(
    "credit",
    [
        {
            "type": "Person",
            "person": {"id": "https://orcid.org/0000-0002-1825-0097"},
            "roles": ["Author"],
        },
        {
            "type": "Organization",
            "organization": {"id": "https://ror.org/03yrm5c26"},
            "roles": ["Author"],
        },
    ],
)
def test_text_writers_explicitly_reject_authors_without_names(file_format, credit):
    value = local_work(contributors=[credit])
    with pytest.raises(ValueError, match="name"):
        export_bibliography_records([value], file_format)
    assert json.loads(export_bibliography_records([value], "commonmeta")) == [value]


@pytest.mark.parametrize("invalid", [{"author": ["Jane Smith"]}, {"issued": "2024"}])
def test_malformed_csl_records_do_not_discard_valid_siblings(invalid):
    valid = {"id": "https://doi.org/10.1234/valid", "type": "article-journal", "title": "Valid"}
    records, diagnostics = parse_bibliography_records(
        json.dumps([valid | invalid, valid]), "csl-json"
    )
    assert [record.work["title"] for record in records] == ["Valid"]
    assert [(row["row"], row["code"]) for row in diagnostics if row["severity"] == "error"] == [
        (1, "invalid_record")
    ]


def test_unsupported_csl_writer_types_are_explicit_errors():
    with pytest.raises(ValueError, match="CSL"):
        work_to_csl_json(local_work(type="ProceedingsArticle"))


def test_every_standard_work_type_exports_valid_csl_or_is_explicitly_unsupported():
    from commonmeta.schema_utils import json_schema_errors
    from inquiro.work import work_schema

    for work_type in work_schema()["$defs"]["type"]["enum"]:
        try:
            entry = work_to_csl_json(local_work(type=work_type))
        except ValueError as error:
            assert "CSL" in str(error)
        else:
            assert json_schema_errors(entry, "csl") is None, work_type


@pytest.mark.parametrize("bad_first", [False, True])
def test_undefined_bibtex_macro_is_a_per_record_diagnostic(bad_first):
    bad = "@article{bad,title=undefinedmacro}"
    valid = '@string{validtitle = "Valid macro"}\n@article{good,title=validtitle # " title",month=jan,year={2024},doi={10.1234/good}}'
    records, errors = parse_bibliography_records(
        "\n".join([bad, valid] if bad_first else [valid, bad]), "bibtex"
    )
    assert [(record.citation_key, record.work["title"]) for record in records] == [
        ("good", "Valid macro title")
    ]
    assert [(row["row"], row["code"]) for row in errors if row["severity"] == "error"] == [
        (1 if bad_first else 2, "invalid_record")
    ]


@pytest.mark.parametrize("field", ["author", "editor"])
@pytest.mark.parametrize(
    "name,family,given,suffix",
    [
        ("von Neumann, Jr., John", "von Neumann", "John", "Jr."),
        ("{von Neumann}, Jr., John", "von Neumann", "John", "Jr."),
        ("de la Cruz, III, Juan", "de la Cruz", "Juan", "III"),
    ],
)
def test_bibtex_three_part_names_preserve_suffix_semantics(field, name, family, given, suffix):
    content = f"@article{{source,title={{Example}},{field}={{{name}}}}}"
    records, diagnostics = parse_bibliography_records(content, "bibtex")
    assert len(records) == 1 and not any(row["severity"] == "error" for row in diagnostics)
    csl_field = "author" if field == "author" else "editor"
    expected = {"family": family, "given": given, "suffix": suffix}
    assert work_to_csl_json(records[0].work)[csl_field] == [expected]
    if field == "author":
        exported = export_bibliography_records([records[0].work], "bibtex")
        restored, errors = parse_bibliography_records(exported, "bibtex")
        assert len(restored) == 1 and not any(row["severity"] == "error" for row in errors)
        assert work_to_csl_json(restored[0].work)["author"] == [expected]


@pytest.mark.parametrize("bad_first", [False, True])
def test_skipped_malformed_bibtex_entry_has_a_diagnostic_and_keeps_valid_sibling(bad_first):
    bad = "@article{bad,title={Invalid}"
    valid = "@article{good,title={Valid sibling},doi={10.1234/good}}"
    records, diagnostics = parse_bibliography_records(
        "\n".join([bad, valid] if bad_first else [valid, bad]), "bibtex"
    )
    assert [(record.citation_key, record.work["title"], record.row) for record in records] == [
        ("good", "Valid sibling", 2 if bad_first else 1)
    ]
    assert [(row["row"], row["code"]) for row in diagnostics if row["severity"] == "error"] == [
        (1 if bad_first else 2, "invalid_record")
    ]


def test_bibtex_diagnostics_distinguish_comments_and_macro_text_from_skipped_entries():
    content = """\ufeff
Free text and an email address me@example.org
@reference is a handle in a plain comment
@comment{@article{ignored,title={Example}}}
@preamble{"Note @article{also ignored}"}
@string{label = "Title @article{inside a field}"}
@article{first,title=label}
@article{bad,title={Invalid}
@article{last,title={Last}}
"""
    records, diagnostics = parse_bibliography_records(content, "bibtex")
    assert [(record.citation_key, record.row) for record in records] == [("first", 1), ("last", 3)]
    assert records[0].work["title"] == "Title @articleinside a field"
    assert [(row["row"], row["code"]) for row in diagnostics if row["severity"] == "error"] == [
        (2, "invalid_record")
    ]


def test_unsupported_bibtex_entry_is_diagnosed_instead_of_silently_skipped():
    content = "@unknown{unsupported,title={Unsupported}}\n@article{valid,title={Valid}}"
    records, diagnostics = parse_bibliography_records(content, "bibtex")
    assert [(record.citation_key, record.row) for record in records] == [("valid", 2)]
    assert [(row["row"], row["code"]) for row in diagnostics if row["severity"] == "error"] == [
        (1, "invalid_record")
    ]


@pytest.mark.parametrize("name", ["Smith, Jr., John, Extra", "Smith, John\\"])
def test_malformed_bibtex_name_is_a_record_diagnostic(name):
    content = f"@article{{bad,title={{Invalid name}},author={{{name}}}}}\n@article{{good,title={{Valid}}}}"
    records, diagnostics = parse_bibliography_records(content, "bibtex")
    assert [record.citation_key for record in records] == ["good"]
    assert [(row["row"], row["code"]) for row in diagnostics if row["severity"] == "error"] == [
        (1, "invalid_record")
    ]


@pytest.mark.parametrize(
    "resource_id,expected",
    [
        ("https://www.ncbi.nlm.nih.gov/pubmed/42", {("pmid", "42")}),
        ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC42/", {("pmcid", "PMC42")}),
        ("https://www.ncbi.nlm.nih.gov/books/42/", set()),
        ("https://pmc.ncbi.nlm.nih.gov/articles/PMC42/", {("pmcid", "PMC42")}),
        ("https://pmc.ncbi.nlm.nih.gov/not-an-article/42", set()),
    ],
)
def test_ncbi_work_url_matching_respects_the_resource_path(resource_id, expected):
    assert work_identifiers(local_work(id=resource_id)) == expected


def test_crossref_license_does_not_break_csl_or_mutate_the_work():
    from commonmeta.schema_utils import json_schema_errors
    from inquiro.work import read_work

    value = read_work(
        {
            "DOI": "10.1234/licensed",
            "type": "journal-article",
            "title": ["Licensed article"],
            "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
        },
        "crossref",
    )
    original = deepcopy(value)
    entry = work_to_csl_json(value)
    assert json_schema_errors(entry, "csl") is None
    assert "copyright" not in entry
    assert "Licensed article" in render_citation(value, builtin_style_xml("apa"))
    assert (
        json.loads(export_bibliography_records([value], "csl-json"))[0]["title"]
        == "Licensed article"
    )
    assert value == original
    assert json.loads(export_bibliography_records([value], "commonmeta")) == [original]


def test_csl_export_disambiguates_shared_work_ids_for_citeproc_consumers():
    from citeproc.source.json import CiteProcJSON

    values = [
        local_work(id="https://doi.org/10.1234/shared", title=title) for title in ["Zebra", "Apple"]
    ]
    original = deepcopy(values)
    entries = json.loads(
        export_bibliography_records(values, "csl-json", citation_keys=["manual", "manual"])
    )
    assert [entry["id"] for entry in entries] == ["manual", "manuala"]
    source = CiteProcJSON(entries)
    assert "".join(source["manual"]["title"]) == "Zebra"
    assert "".join(source["manuala"]["title"]) == "Apple"
    assert all(entry["DOI"] == "10.1234/shared" for entry in entries)
    assert values == original


@pytest.mark.parametrize("source_id", [0, 1, -1, 1.5])
def test_numeric_csl_ids_import_without_mutating_the_input(source_id):
    from inquiro.work import read_work

    value = {"id": source_id, "type": "article-journal", "title": "Numeric ID"}
    original = deepcopy(value)
    assert isinstance(read_work(value, "csl")["id"], str)
    records, diagnostics = parse_bibliography_records(
        json.dumps([value, value | {"id": "https://doi.org/10.1234/sibling", "title": "Sibling"}]),
        "csl-json",
    )
    assert [record.work["title"] for record in records] == ["Numeric ID", "Sibling"]
    assert records[0].work["id"].startswith("urn:uuid:")
    assert not any(row["severity"] == "error" for row in diagnostics)
    assert value == original


@pytest.mark.parametrize(
    "tag,value",
    [
        ("T1", "State-of-the-art analysis"),
        ("DO", "10.1000/foo-bar"),
        ("AU", "Jean-Pierre Smith"),
        ("AB", "A well-known result"),
        ("UR", "https://example.org/full-text"),
    ],
)
def test_ris_hyphenated_values_cannot_silently_truncate_and_commit(tag, value):
    bad = f"TY  - JOUR\nT1  - Unsafe record\n{tag}  - {value}\nER  - "
    good = "TY  - JOUR\nT1  - Safe sibling\nDO  - 10.1000/good\nER  - "
    records, diagnostics = parse_bibliography_records(f"{bad}\n{good}", "ris")
    assert [record.work["title"] for record in records] == ["Safe sibling"]
    assert any(
        row.get("row") == 1 and row["code"] == "invalid_record" and "hyphen" in row["message"]
        for row in diagnostics
    )


@pytest.mark.parametrize(
    "titles", ["TI  - Standard title", "TI  - Standard title\nT1  - Standard title"]
)
def test_ris_standard_title_aliases_import_without_loss(titles):
    records, diagnostics = parse_bibliography_records(
        f"TY  - JOUR\n{titles}\nDO  - 10.1000/title\nER  - ", "ris"
    )
    assert not any(row["severity"] == "error" for row in diagnostics)
    assert len(records) == 1 and records[0].work["title"] == "Standard title"


@pytest.mark.parametrize("local_id", ["Doe2024", "smith2024", 1, 0])
@pytest.mark.parametrize("doi", [None, "10.1000/example"])
def test_csl_local_ids_do_not_replace_or_invent_bibliographic_identifiers(local_id, doi):
    from inquiro.work import read_work

    payload = {
        "id": local_id,
        "type": "article-journal",
        "title": "Local CSL key",
        **({"DOI": doi} if doi else {}),
    }
    before = deepcopy(payload)
    work = read_work(payload, "csl")
    assert work_identifiers(work) == ({("doi", doi)} if doi else set())
    if doi:
        assert work["id"] == f"https://doi.org/{doi}"
    else:
        assert work["id"].startswith("urn:uuid:")
    assert payload == before


def test_csl_export_and_reimport_retains_explicit_doi_for_citation_keys():
    value = local_work(id="https://doi.org/10.1000/example")
    for key in ("Doe2024", "smith2024"):
        output = export_bibliography_records([value], "csl-json", citation_keys=[key])
        records, diagnostics = parse_bibliography_records(output, "csl-json")
        assert not any(row["severity"] == "error" for row in diagnostics)
        assert work_identifiers(records[0].work) == {("doi", "10.1000/example")}


@pytest.mark.parametrize(
    "endpoints,expected",
    [
        ([[2020, 1, 1], [2022, 5, 20]], None),
        ([[2020, 1, 1], [2020, 1, 20]], "2020-01"),
        ([[2020, 1, 1], [2020, 5, 20]], "2020"),
        ([[2020], [2020, 1, 20]], "2020"),
        ([[2020, 1], [2020, 1, 20]], "2020-01"),
    ],
)
def test_csl_ranges_retain_only_common_year_or_month(endpoints, expected):
    from inquiro.work import read_work

    payload = {
        "id": "https://doi.org/10.1000/range",
        "type": "article-journal",
        "title": "Date range",
        "issued": {"date-parts": endpoints},
    }
    before = deepcopy(payload)
    value = read_work(payload, "csl")
    assert value.get("date_published") == expected
    assert work_to_csl_json(value).get("issued") == (
        {"date-parts": [[int(part) for part in expected.split("-")]]} if expected else None
    )
    assert payload == before


def test_versioned_software_cannot_silently_export_as_a_book():
    value = local_work(type="Software", version="1.0")
    with pytest.raises(ValueError, match="Software"):
        work_to_csl_json(value)
    with pytest.raises(ValueError, match="Software"):
        export_bibliography_records([value], "csl-json")
    assert json.loads(export_bibliography_records([value], "commonmeta")) == [value]
    assert work_to_csl_json(local_work(type="Software"))["type"] == "software"


@pytest.mark.parametrize(
    "organization",
    [
        "Research and Development Corp.",
        "World Health Organization",
        "Institute, Division A",
        "R&D 50% Council",
    ],
)
def test_bibtex_organization_authors_remain_single_literal_credits(organization):
    from io import StringIO

    from citeproc.source.bibtex import BibTeX

    value = local_work(
        contributors=[
            {
                "type": "Person",
                "person": {"family_name": "Smith", "given_name": "Jane"},
                "roles": ["Author"],
            },
            {"type": "Organization", "organization": {"name": organization}, "roles": ["Author"]},
        ]
    )
    original = deepcopy(value)
    output = export_bibliography_records([value], "bibtex", citation_keys=["authors"])
    authors = BibTeX(StringIO(output))["authors"]["author"]
    assert len(authors) == 2
    assert "".join(authors[0]["family"]) == "Smith"
    assert "".join(authors[0]["given"]) == "Jane"
    assert "".join(authors[1]["family"]) == organization
    assert not authors[1].get("given")
    assert value == original
    assert json.loads(export_bibliography_records([value], "commonmeta")) == [original]

    records, diagnostics = parse_bibliography_records(output, "bibtex")
    assert len(records) == 1, diagnostics
    credits = records[0].work["contributors"]
    assert len(credits) == 2
    assert credits[0]["person"]["family_name"] == "Smith"
    assert credits[0]["person"]["given_name"] == "Jane"
    assert credits[1] == {
        "type": "Organization",
        "organization": {"name": organization},
        "roles": ["Author"],
    }


@pytest.mark.parametrize("key", ["smith2024", "2024", "local-key"])
@pytest.mark.parametrize("doi", [None, "10.1000/research"])
def test_bibtex_local_keys_do_not_determine_work_identity_or_type(key, doi):
    content = f"@article{{{key},title={{Research}}"
    content += f",doi={{{doi}}}" if doi else ""
    records, diagnostics = parse_bibliography_records(content + "}", "bibtex")
    assert len(records) == 1, diagnostics
    record = records[0]
    assert record.citation_key == key
    assert record.work["type"] == "JournalArticle"
    assert record.work["title"] == "Research"
    assert (
        record.work["id"] == f"https://doi.org/{doi}"
        if doi
        else record.work["id"].startswith("urn:uuid:")
    )
    assert not record.work.get("identifiers")


@pytest.mark.parametrize(
    "title",
    [
        "A <i>great</i> result",
        "A <i>50%</i> improvement in R&amp;D costs",
        "Unclosed {brace",
        "Closing } brace",
        r"Use C:\data^2",
        "<b>café</b> 的 $H_2O$",
        r"$\mathbf{X}_2$",
    ],
)
def test_bibtex_formatted_titles_survive_export_and_reimport(title):
    value = local_work(title=title, id="https://doi.org/10.1000/title")
    output = export_bibliography_records([value], "bibtex", citation_keys=["formatted"])
    records, diagnostics = parse_bibliography_records(output, "bibtex")
    assert len(records) == 1, diagnostics
    assert records[0].work["title"] == value["title"]


def test_bibtex_protected_authors_and_editors_preserve_roles_and_person_name_groups():
    content = r"""@article{smith2024,
        title={A \textit{great} result},
        author={{Research and {Development} Corp.} and Smith, {J}ane},
        editor={{Institute, Division A} and Doe, Joe}
    }"""
    records, diagnostics = parse_bibliography_records(content, "bibtex")
    assert len(records) == 1, diagnostics
    assert records[0].work["contributors"] == [
        {
            "type": "Organization",
            "organization": {"name": "Research and Development Corp."},
            "roles": ["Author"],
        },
        {
            "type": "Person",
            "person": {"family_name": "Smith", "given_name": "Jane"},
            "roles": ["Author"],
        },
        {
            "type": "Organization",
            "organization": {"name": "Institute, Division A"},
            "roles": ["Editor"],
        },
        {
            "type": "Person",
            "person": {"family_name": "Doe", "given_name": "Joe"},
            "roles": ["Editor"],
        },
    ]


def test_bibtex_text_projection_converts_markup_and_escapes_tex_characters():
    import bibtexparser

    value = local_work(
        type="BookChapter",
        title="A <i>50%</i> improvement in R&amp;D costs",
        description="<p>See <b>Table #1</b> &amp; data_set ~ $5.</p>",
        container={
            "type": "Book",
            "title": "Methods in <i>R&amp;D</i>",
            "series": "Series #1",
            "location": "City & Coast",
        },
        publisher={"name": "R&D Press"},
    )
    original = deepcopy(value)
    output = export_bibliography_records([value], "bibtex", citation_keys=["safe"])
    entry = bibtexparser.loads(output).entries[0]
    assert entry["title"] == r"A \textit{50\%} improvement in R\&D costs"
    assert entry["abstract"] == r"See \textbf{Table \#1} \& data\_set \textasciitilde{} \$5."
    assert entry["booktitle"] == r"Methods in \textit{R\&D}"
    assert entry["publisher"] == r"R\&D Press"
    assert entry["series"] == r"Series \#1"
    assert entry["location"] == r"City \& Coast"
    assert value == original
    assert json.loads(export_bibliography_records([value], "commonmeta")) == [original]


def test_ris_display_fields_are_plaintext_without_changing_work_or_identifiers():
    value = local_work(
        id="https://doi.org/10.1234/A%253c",
        type="JournalArticle",
        title="<i>Study</i>\nResults &amp; tables",
        description="<p>First</p>\r\nSecond<script>hidden()</script>",
        container={
            "title": "<b>Journal</b>\nPart",
            "volume": "2\nB",
            "issue": "<i>3</i>",
            "first_page": "<b>10</b>",
            "last_page": "20",
        },
        publisher={"name": "<i>Research</i>\nPress"},
        contributors=[
            {
                "type": "Person",
                "person": {"family_name": "<b>Smith</b>", "given_name": "Jane\nAnn"},
                "roles": ["Author"],
            },
            {
                "type": "Organization",
                "organization": {"name": "<i>Council</i>\nGroup"},
                "roles": ["Author"],
            },
        ],
        subjects=[{"subject": "<b>Graph</b>\nTheory"}],
        url="https://example.org/Study?first=1&second=2",
    )
    original = deepcopy(value)
    output = export_bibliography_records([value], "ris")
    assert output.splitlines() == [
        "TY  - JOUR",
        "T1  - Study Results & tables",
        "T2  - Journal Part",
        "AU  - Smith, Jane Ann",
        "AU  - Council Group",
        "DO  - 10.1234/a%3c",
        "UR  - https://example.org/Study?first=1&second=2",
        "AB  - First Second",
        "KW  - Graph Theory",
        "PB  - Research Press",
        "VL  - 2 B",
        "IS  - 3",
        "SP  - 10",
        "EP  - 20",
        "ER  - ",
    ]
    assert value == original
    assert json.loads(export_bibliography_records([value], "commonmeta")) == [original]


@pytest.mark.parametrize(
    "description", ["First\nSecond", "First\r\nSecond", "<p>First</p><p>Second</p>"]
)
def test_ris_multiline_display_text_can_be_reimported(description):
    value = local_work(
        id="https://doi.org/10.1234/study", title="<i>Study</i>", description=description
    )
    original = deepcopy(value)
    records, diagnostics = parse_bibliography_records(
        export_bibliography_records([value], "ris"), "ris"
    )
    assert not any(row["severity"] == "error" for row in diagnostics)
    assert len(records) == 1
    assert records[0].work["title"] == "Study"
    assert records[0].work["description"] == "First Second"
    assert work_identifiers(records[0].work) == {("doi", "10.1234/study")}
    assert value == original


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Unclosed {brace", r"Unclosed \textbraceleft{}brace"),
        ("Closing } brace", r"Closing \textbraceright{} brace"),
        (r"Use C:\data^2", r"Use C:\textbackslash{}data\textasciicircum{}2"),
        ("<b>café</b> 的 $H_2O$", r"\textbf{café} 的 $H_2O$"),
    ],
)
def test_bibtex_text_projection_cannot_break_record_structure(title, expected):
    import bibtexparser

    values = [local_work(title=title), local_work(title="Valid sibling")]
    output = export_bibliography_records(values, "bibtex", citation_keys=["first", "second"])
    entries = bibtexparser.loads(output).entries
    assert {entry["ID"]: entry["title"] for entry in entries} == {
        "first": expected,
        "second": "Valid sibling",
    }


@pytest.mark.parametrize("output_format", ["text", "html"])
def test_citations_sanitize_temporary_rich_text_and_keep_stored_work(output_format):
    value = local_work(
        title='Research<script>alert(1)</script><i onclick="alert(2)">Safe title</i><img src=x onerror=alert(3)>',
    )
    original = deepcopy(value)
    result = render_citation(value, builtin_style_xml("apa"), output_format=output_format)
    assert "Research" in result and "Safe title" in result
    assert "script" not in result and "onclick" not in result and "onerror" not in result
    assert "alert(" not in result and "<img" not in result
    if output_format == "html":
        assert "<i>" in result
    else:
        assert "<i>" not in result
    assert value == original
    assert json.loads(export_bibliography_records([value], "commonmeta")) == [original]
