import pytest
from inquiro.bibliography import (
    BibliographyExportOptions,
    BibliographyRecord,
    CitationKeyFormulaError,
    Contributor,
    evaluate_citation_key_formula,
    export_bibliography_records,
    parse_bibliography_records,
)


def test_bibtex_import_preserves_braced_case_identifiers_and_custom_fields():
    source = """@article{braced,
      title = {{An {API} for GraphQL}},
      author = {Doe, Jane},
      openalex = {W123},
      arxiv = {2401.00001},
      dataset_id = {DS-42}
    }"""

    records, errors = parse_bibliography_records(source, "bibtex")

    assert errors == []
    assert records[0].title == "An API for GraphQL"
    assert records[0].citation_key == "braced"
    assert dict(records[0].identifiers) == {
        "openalex": "W123",
        "arxiv": "2401.00001",
    }
    assert dict(records[0].custom_fields) == {"dataset_id": "DS-42"}


def test_bibtex_import_decodes_protected_accents_alongside_unicode():
    source = r"""@article{accented,
      title = {Example},
      author = {Garc{\'i}a, Ada},
      journal = {Revista de F\'isica Café}
    }"""

    records, errors = parse_bibliography_records(source, "bibtex")

    assert errors == []
    assert records[0].authors == (Contributor("García", "Ada"),)
    assert records[0].publication_title == "Revista de Física Café"


def test_bibtex_import_resolves_concatenated_macros_and_literals():
    source = """@string{prefix = "Deep"}
    @string{suffix = "Learning"}
    @article{concat,
      title = prefix # " " # suffix,
      journal = "Journal of " # suffix
    }"""

    records, errors = parse_bibliography_records(source, "bibtex")

    assert errors == []
    assert records[0].title == "Deep Learning"
    assert records[0].publication_title == "Journal of Learning"


def test_bibtex_import_resolves_predefined_month_macros_in_concatenations():
    source = """@article{months,
      title = "Proceedings of " # jan,
      month = jan # " 12"
    }"""

    records, errors = parse_bibliography_records(source, "bibtex")

    assert errors == []
    assert records[0].title == "Proceedings of January"
    assert ("month", "January 12") in records[0].custom_fields


def test_bibtex_import_rejects_unresolvable_concatenation():
    records, errors = parse_bibliography_records(
        '@article{broken, title = missing_macro # " title"}',
        "bibtex",
    )

    assert records == []
    assert any("undefined string macro 'missing_macro'" in error["message"] for error in errors)


def test_bibtex_literal_author_survives_item_storage_serialization():
    source = r"""@report{who,
      title = {Global health guidance},
      author = {{World Health Organization}}
    }"""

    records, errors = parse_bibliography_records(source, "bibtex")

    assert errors == []
    assert records[0].authors == (Contributor("World Health Organization"),)
    assert records[0].authors[0].storage_name() == "{World Health Organization}"
    stored_contributor = Contributor.parse(records[0].authors[0].storage_name())
    assert stored_contributor == records[0].authors[0]

    output = export_bibliography_records(
        [BibliographyRecord("who", "report", "Global health guidance", (stored_contributor,))],
        "bibtex",
    )
    round_trip, round_trip_errors = parse_bibliography_records(output, "bibtex")
    assert round_trip_errors == []
    assert round_trip[0].authors == records[0].authors


def test_import_reports_each_missing_title():
    records, errors = parse_bibliography_records("TY  - JOUR\nAU  - Nobody\nER  -\n", "ris")

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
    records, errors = parse_bibliography_records(source, "endnote")

    assert errors == []
    assert len(records) == 2
    assert records[0].title == "First Paper"
    assert records[1].title == "Second Book"
    assert records[1].reference_type == "book"


def test_biblatex_uses_native_types_and_fields():
    record = BibliographyRecord(
        citation_key="doe2026data",
        reference_type="dataset",
        title="Café 数据",
        authors=(Contributor("de Doe", "Jane"),),
        publication_date="2026-08-25",
        publication_title="Data Journal",
        location="Shanghai",
        doi="10.1234/data",
        urls=("https://example.test/data",),
        identifiers=(("arxiv", "2608.00001"),),
    )

    output = export_bibliography_records(
        [record],
        "biblatex",
        options=BibliographyExportOptions(include_identifiers=True),
    )

    assert "@dataset{doe2026data" in output
    assert "journaltitle = {Data Journal}" in output
    assert "date = {2026-08-25}" in output
    assert "location = {Shanghai}" in output
    assert "eprint = {2608.00001}" in output


def test_biblatex_import_preserves_standard_item_metadata():
    source = """@article{complete,
      title = {Complete metadata},
      volume = {12},
      number = {3},
      pages = {4--9},
      publisher = {Example Press},
      location = {Shanghai}
    }"""

    records, errors = parse_bibliography_records(source, "biblatex")

    assert errors == []
    record = records[0]
    assert record.title == "Complete metadata"
    assert record.volume == "12"
    assert record.issue == "3"
    assert record.pages == "4--9"
    assert record.publisher == "Example Press"
    assert record.location == "Shanghai"


@pytest.mark.parametrize("biblatex_type", ["online", "dataset", "report"])
def test_biblatex_entry_types_survive_cross_format_export(biblatex_type):
    records, errors = parse_bibliography_records(
        f"@{biblatex_type}{{cross-format, title = {{Cross-format export}}}}",
        "biblatex",
    )

    output = export_bibliography_records(records, "bibtex")

    assert errors == []
    assert output.startswith(f"@{biblatex_type}{{cross-format")


@pytest.mark.parametrize(
    ("entry_type", "expected"),
    [
        ("online", "webpage"),
        ("inproceedings", "conference"),
        ("incollection", "chapter"),
    ],
)
def test_biblatex_import_normalizes_native_entry_types(entry_type, expected):
    records, errors = parse_bibliography_records(
        f"@{entry_type}{{sample, title = {{Native type}}}}",
        "biblatex",
    )

    assert errors == []
    assert records[0].reference_type == expected


@pytest.mark.parametrize("file_format", ["bibtex", "biblatex"])
def test_bib_export_disambiguates_duplicate_citation_keys(file_format):
    records = [
        BibliographyRecord("same", "article", "First"),
        BibliographyRecord("same", "article", "Second"),
    ]

    output = export_bibliography_records(records, file_format)
    round_trip, errors = parse_bibliography_records(output, file_format)

    assert errors == []
    assert [(record.citation_key, record.title) for record in round_trip] == [
        ("same", "First"),
        ("samea", "Second"),
    ]


@pytest.mark.parametrize("file_format", ["bibtex", "biblatex"])
def test_bib_export_reserves_key_length_for_collision_suffix(file_format):
    base = "0" * 255
    records = [BibliographyRecord(base, "article", f"Record {number}") for number in range(28)]

    output = export_bibliography_records(records, file_format)
    round_trip, errors = parse_bibliography_records(output, file_format)

    assert errors == []
    keys = [record.citation_key for record in round_trip]
    assert keys[0] == base
    assert keys[1] == f"{'0' * 254}a"
    assert keys[-1] == f"{'0' * 253}aa"
    assert all(len(record.citation_key or "") <= 255 for record in round_trip)


@pytest.mark.parametrize("file_format", ["bibtex", "biblatex"])
def test_bib_export_doi_omit_policy_overrides_included_identifiers(file_format):
    record = BibliographyRecord(
        citation_key="doe2026",
        reference_type="article",
        title="DOI policy",
        doi="10.1234/hidden",
        identifiers=(("doi", "10.1234/hidden"), ("pmid", "12345")),
    )

    output = export_bibliography_records(
        [record],
        file_format,
        options=BibliographyExportOptions(
            include_identifiers=True,
            doi_policy="omit",
        ),
    )

    assert "10.1234/hidden" not in output
    assert "pmid" in output


@pytest.mark.parametrize("file_format", ["bibtex", "biblatex"])
def test_bib_export_only_includes_supported_identifier_providers(file_format):
    record = BibliographyRecord(
        citation_key="doe2026",
        reference_type="article",
        title="Canonical title",
        publication_date="2026",
        urls=("https://example.test/canonical",),
        identifiers=(
            ("title", "external-title"),
            ("semantic_scholar", "S2-123"),
            ("open-alex", "invalid-provider-spelling"),
            ("openalex", "W1"),
            ("OPENALEX", "W2"),
            ("arxiv", "2608.00001"),
        ),
    )

    output = export_bibliography_records(
        [record],
        file_format,
        options=BibliographyExportOptions(include_identifiers=True),
    )

    assert "title = {Canonical title}" in output
    assert "external-title" not in output
    assert "semantic_scholar" not in output
    assert "invalid-provider-spelling" not in output
    assert "openalex = {W1}" in output
    assert "W2" not in output
    if file_format == "biblatex":
        assert "eprint = {2608.00001}" in output
    else:
        assert "arxiv = {2608.00001}" in output


def test_latex_encoding_preserves_unmappable_cjk():
    record = BibliographyRecord(
        citation_key="garcia2026",
        reference_type="article",
        title="García 的 café & data",
    )
    output = export_bibliography_records(
        [record], "bibtex", options=BibliographyExportOptions(encoding="latex")
    )
    assert "的" in output
    assert "\\'" in output


@pytest.mark.parametrize("file_format", ["bibtex", "biblatex"])
def test_bib_export_escapes_special_characters_exactly_once(file_format):
    record = BibliographyRecord(
        citation_key="special",
        reference_type="article",
        title="A & B_#% with <i>C & D</i>",
        abstract="50% of A_B & C#",
    )

    output = export_bibliography_records([record], file_format)
    round_trip, errors = parse_bibliography_records(output, file_format)

    assert r"title = {A \& B\_\#\% with \textit{C \& D}}" in output
    assert r"abstract = {50\% of A\_B \& C\#}" in output
    assert r"\\&" not in output
    assert errors == []
    assert round_trip[0].title == "A &amp; B_#% with <i>C &amp; D</i>"
    assert round_trip[0].abstract == "50% of A_B &amp; C#"


@pytest.mark.parametrize("file_format", ["bibtex", "biblatex"])
def test_bib_export_keeps_paired_currency_dollars_out_of_math(file_format):
    record = BibliographyRecord(
        citation_key="costs",
        reference_type="article",
        title="Costs $5 and $10",
    )

    output = export_bibliography_records([record], file_format)
    round_trip, errors = parse_bibliography_records(output, file_format)

    assert r"title = {Costs \$5 and \$10}" in output
    assert errors == []
    assert round_trip[0].title == record.title


def test_latex_encoded_contributors_round_trip_with_control_word_boundaries():
    record = BibliographyRecord(
        citation_key="garcia",
        reference_type="article",
        title="Café 的 Física",
        authors=(Contributor("García", "Física"),),
    )

    output = export_bibliography_records(
        [record], "bibtex", options=BibliographyExportOptions(encoding="latex")
    )
    round_trip, errors = parse_bibliography_records(output, "bibtex")

    assert r"author = {Garc{\'\i}a, F{\'\i}sica}" in output
    assert errors == []
    assert round_trip[0].title == record.title
    assert round_trip[0].authors == record.authors


def test_bibtex_rich_text_import_and_export_are_semantic():
    source = r"""@article{rich,
      title = {An \emph{important} H\textsubscript{2}O result},
      abstract = {Uses \textbf{strong} evidence}
    }"""

    records, errors = parse_bibliography_records(source, "bibtex")

    assert errors == []
    assert records[0].title == "An <i>important</i> H<sub>2</sub>O result"
    assert records[0].abstract == "Uses <b>strong</b> evidence"

    output = export_bibliography_records(
        [
            BibliographyRecord(
                citation_key="rich",
                reference_type="article",
                title=records[0].title,
                abstract=records[0].abstract,
            )
        ],
        "biblatex",
    )

    assert r"title = {An \textit{important} H\textsubscript{2}O result}" in output
    assert r"abstract = {Uses \textbf{strong} evidence}" in output


def test_bibtex_title_requires_visible_text_after_rich_text_conversion():
    records, errors = parse_bibliography_records(r"@article{empty, title = {\emph{}}}", "bibtex")

    assert len(records) == 1
    assert errors == [{"row": 1, "message": "Title is required"}]


def test_bibtex_import_reports_failed_blocks_without_discarding_valid_entries():
    source = "@article{valid, title={Valid}}\n@article{broken, title={Truncated}"

    records, errors = parse_bibliography_records(source, "bibtex")

    assert [record.citation_key for record in records] == ["valid"]
    assert errors == [
        {"row": 2, "message": "Cannot parse record: Unexpectedly reached end of file."}
    ]


@pytest.mark.parametrize("file_format", ["bibtex", "biblatex"])
def test_bib_export_uses_native_writer_for_escaped_literal_braces(file_format):
    record = BibliographyRecord(
        citation_key="notation",
        reference_type="article",
        title=r"Set \{ notation",
    )

    output = export_bibliography_records([record], file_format)
    round_trip, errors = parse_bibliography_records(output, file_format)

    assert r"title = {Set \{ notation}" in output
    assert errors == []
    assert round_trip[0].title == "Set { notation"


def test_citation_key_formula_rejects_oversized_numeric_arguments():
    record = BibliographyRecord("record", "article", "A title")

    with pytest.raises(CitationKeyFormulaError, match="numeric formula arguments"):
        evaluate_citation_key_formula(f"authors({'1' * 5000})", record)


def test_export_preserves_escaped_unmatched_braces():
    source = r"@article{brace, title = {Escaped \{ literal}}"
    records, errors = parse_bibliography_records(source, "bibtex")
    assert errors == []

    output = export_bibliography_records(records, "bibtex")
    round_trip, round_trip_errors = parse_bibliography_records(output, "bibtex")

    assert round_trip_errors == []
    assert round_trip[0].title == records[0].title


def test_manual_bibtex_entry_type_is_preserved():
    record = BibliographyRecord(
        citation_key="manual",
        reference_type="article",
        bibtex_type="misc",
        title="Manual type",
    )

    output = export_bibliography_records([record], "bibtex")

    assert "@misc{manual" in output


def test_citation_key_formula_dsl_and_validation():
    record = BibliographyRecord(
        citation_key=None,
        reference_type="article",
        title="The Étude of APIs",
        authors=(Contributor("García", "Ada"), Contributor("Doe", "Jane")),
        publication_date="2026",
    )
    assert (
        evaluate_citation_key_formula(
            'authors(2).fold.alphanum + "-" + year + shorttitle(1).fold.capitalize',
            record,
            force_ascii=True,
        )
        == "GarciaDoe-2026Etude"
    )
    with pytest.raises(CitationKeyFormulaError):
        evaluate_citation_key_formula("auth + unknown", record)


@pytest.mark.parametrize("file_format", ["bibtex", "biblatex"])
def test_bib_export_applies_citation_key_formula_to_keyless_records(file_format):
    records = [
        BibliographyRecord(
            citation_key=None,
            reference_type="article",
            title="Analytical Engine",
            authors=(Contributor("Lovelace", "Ada"),),
            publication_date="1843",
        ),
        BibliographyRecord(
            citation_key=None,
            reference_type="article",
            title="Analytical Engine",
            authors=(Contributor("Lovelace", "Ada"),),
            publication_date="1843",
        ),
        BibliographyRecord(
            citation_key="manual1843",
            reference_type="article",
            title="Kept",
            authors=(Contributor("Doe", "Jane"),),
            publication_date="1843",
        ),
    ]

    output = export_bibliography_records(
        records,
        file_format,
        options=BibliographyExportOptions(
            citation_key_formula="auth.lower + year",
            citation_key_force_ascii=True,
        ),
    )
    round_trip, errors = parse_bibliography_records(output, file_format)

    assert errors == []
    assert [record.citation_key for record in round_trip] == [
        "lovelaceXXXX",
        "lovelaceXXXXa",
        "manual1843",
    ]


@pytest.mark.parametrize("file_format", ["bibtex", "biblatex"])
def test_bib_export_rejects_invalid_citation_key_formula(file_format):
    record = BibliographyRecord(citation_key="manual-key", reference_type="article", title="X")

    with pytest.raises(CitationKeyFormulaError):
        export_bibliography_records(
            [record],
            file_format,
            options=BibliographyExportOptions(citation_key_formula="auth + unknown"),
        )


@pytest.mark.parametrize("file_format", ["ris", "endnote"])
def test_non_bibtex_exports_honor_doi_policy_and_exclusions(file_format):
    record = BibliographyRecord(
        citation_key="doe2026",
        reference_type="article",
        title="Policy test",
        abstract="Hidden abstract",
        authors=(Contributor("Doe", "Jane"),),
        doi="10.1234/hidden",
    )

    output = export_bibliography_records(
        [record],
        file_format,
        options=BibliographyExportOptions(
            doi_policy="omit",
            excluded_fields=("author", "abstract"),
        ),
    )

    assert "10.1234/hidden" not in output
    assert "Doe, Jane" not in output
    assert "Hidden abstract" not in output


@pytest.mark.parametrize("file_format", ["ris", "endnote"])
def test_non_bibtex_url_exports_round_trip(file_format):
    record = BibliographyRecord(
        citation_key="urls",
        reference_type="article",
        title="URL round trip",
        urls=("https://example.test/article", "https://example.test/pdf"),
    )

    output = export_bibliography_records([record], file_format)
    records, errors = parse_bibliography_records(output, file_format)

    assert errors == []
    assert records[0].urls == record.urls


@pytest.mark.parametrize(
    "reference_type",
    ["chapter", "conference", "dataset", "report", "thesis"],
)
def test_ris_reference_types_round_trip(reference_type):
    record = BibliographyRecord("type", reference_type, "Type round trip")

    output = export_bibliography_records([record], "ris")
    records, errors = parse_bibliography_records(output, "ris")

    assert errors == []
    assert records[0].reference_type == reference_type
