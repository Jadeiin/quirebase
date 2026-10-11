from __future__ import annotations

from dataclasses import replace

import pytest
from inquiro import (
    Affiliation,
    BibliographicMetadata,
    CandidateRecord,
    Contributor,
    CustomField,
    Identifier,
    ResourceLink,
)
from inquiro.metadata import (
    MetadataValidationError,
    merge_metadata_values,
    metadata_bibliography_record,
    metadata_from_values,
    metadata_values,
    record_metadata_values,
)


def _metadata():
    return BibliographicMetadata(
        title="Research",
        authors=(
            Contributor(
                "John Smith Jr",
                family_name="Smith",
                given_name="John",
                suffix="Jr",
                kind="person",
                is_corresponding=True,
                identifiers=(Identifier("orcid", "0000-0002-1825-0097"),),
                affiliations=(
                    Affiliation(
                        "University",
                        identifiers=(Identifier("ror", "03yrm5c26"),),
                        country_code="CN",
                        raw_name="Research Lab, University",
                    ),
                ),
            ),
        ),
        editors=(Contributor("Research Council", kind="organization"),),
        urls=(
            ResourceLink(
                "https://example.test/paper",
                kind="full_text",
                media_type="application/pdf",
                version="publishedVersion",
                license="cc-by",
                is_open_access=True,
                intended_application="text-mining",
            ),
        ),
        identifiers=(Identifier("openalex", "W123"), Identifier("doi", "10.1000/paper")),
        doi="10.1000/paper",
        keywords=("Graph; theory",),
        custom_fields=(CustomField("code", "123"), CustomField("reviewed", False)),
    )


def test_snapshot_round_trip_uses_the_existing_provider_value_types():
    original = _metadata()
    write = metadata_values(original)
    restored = metadata_from_values(
        write.values
        | {
            "doi": original.doi,
            "identifiers": dict(write.identifiers),
        }
    )
    assert restored == original
    assert isinstance(restored.authors[0], Contributor)
    assert isinstance(restored.authors[0].affiliations[0], Affiliation)
    assert isinstance(restored.urls[0], ResourceLink)
    assert "affiliation" not in write.values and "affiliations" not in write.values
    assert restored.custom_fields[0].value == "123"


@pytest.mark.parametrize("role", ["authors", "editors"])
@pytest.mark.parametrize(
    "name_parts",
    [
        {"family_name": " "},
        {"family_name": "\t\n", "given_name": " ", "suffix": " "},
    ],
    ids=["blank-family", "blank-name-parts"],
)
@pytest.mark.parametrize("source", [False, True], ids=["manual", "source"])
def test_duplicate_validation_uses_normalized_contributor_names(role, name_parts, source):
    def validate():
        if source:
            merge_metadata_values(
                BibliographicMetadata("Duplicate credits"),
                {
                    role: [
                        {"display_name": "John Smith", **name_parts},
                        {"display_name": "John Smith"},
                    ],
                },
                merge=True,
            )
        else:
            metadata_values(
                BibliographicMetadata(
                    "Duplicate credits",
                    **{role: (Contributor("John Smith", **name_parts), Contributor("John Smith"))},
                )
            )

    with pytest.raises(MetadataValidationError, match="contributors must be unique"):
        validate()


@pytest.mark.parametrize("role", ["authors", "editors"])
@pytest.mark.parametrize("incoming", [None, []], ids=["omitted", "empty"])
def test_source_contributor_lists_distinguish_unknown_from_explicit_clear(role, incoming):
    update = merge_metadata_values(_metadata(), {role: incoming}, merge=True)
    if incoming is None:
        assert role not in update.values
    else:
        assert update.values[role] == []


@pytest.mark.parametrize("affiliations", [None, []], ids=["unknown", "clear"])
@pytest.mark.parametrize("corresponding", [None, False], ids=["unknown", "explicit-false"])
def test_source_merge_retains_unknown_credit_attributes_and_applies_explicit_values(
    affiliations, corresponding
):
    candidate = CandidateRecord(
        provider="openalex",
        lookup_identifier=Identifier("openalex", "W123"),
        title="Updated",
        authors=(
            Contributor(
                "John Smith",
                family_name="Smith",
                given_name="John",
                affiliations=affiliations,
                is_corresponding=corresponding,
            ),
        ),
    )
    original = _metadata()
    update = merge_metadata_values(original, record_metadata_values(candidate), merge=True)
    restored = metadata_from_values(metadata_values(original).values | update.values)
    credit = restored.authors[0]
    assert credit.suffix == "Jr" and credit.kind == "person"
    assert credit.identifiers == original.authors[0].identifiers
    assert credit.is_corresponding is (corresponding is None)
    assert credit.affiliations == (original.authors[0].affiliations if affiliations is None else ())


def test_ambiguous_suffixes_do_not_inherit_another_contributors_attributes():
    original = _metadata()
    original = replace(
        original,
        authors=(
            original.authors[0],
            Contributor("John Smith Sr", family_name="Smith", given_name="John", suffix="Sr"),
        ),
    )
    update = merge_metadata_values(
        original,
        {
            "authors": [
                {"display_name": "John Smith", "family_name": "Smith", "given_name": "John"}
            ],
        },
        merge=True,
    )
    credit = metadata_from_values(update.values).authors[0]
    assert credit.suffix is None and credit.affiliations is None
    assert credit.is_corresponding is None


def test_source_unknown_affiliations_preserve_a_known_empty_list():
    original = _metadata()
    original = replace(original, authors=(replace(original.authors[0], affiliations=()),))
    update = merge_metadata_values(
        original,
        {"authors": [{"display_name": "John Smith", "family_name": "Smith", "given_name": "John"}]},
        merge=True,
    )
    assert metadata_from_values(update.values).authors[0].affiliations == ()


def test_source_display_name_retains_known_name_parts_and_credit_attributes():
    original = _metadata()
    record = CandidateRecord(
        provider="openalex",
        lookup_identifier=Identifier("openalex", "W123"),
        title=original.title,
        authors=(Contributor("John Smith"),),
    )
    update = merge_metadata_values(original, record_metadata_values(record), merge=True)
    credit = metadata_from_values(update.values).authors[0]
    assert credit == replace(original.authors[0], display_name="John Smith")


@pytest.mark.parametrize("role", ["authors", "editors"])
def test_source_display_name_retains_known_organization_credit_attributes(role):
    original = _metadata()
    organization = replace(
        original.authors[0],
        display_name="World Health Organization",
        family_name=None,
        given_name=None,
        suffix=None,
        kind="organization",
        is_corresponding=None,
    )
    original = replace(original, **{role: (organization,)})
    update = merge_metadata_values(
        original, {role: [{"display_name": organization.display_name}]}, merge=True
    )
    restored = metadata_from_values(metadata_values(original).values | update.values)

    assert getattr(restored, role) == (organization,)
    credit = getattr(metadata_bibliography_record(restored), role)[0]
    assert credit.family_name == organization.display_name
    assert credit.given_name is None


@pytest.mark.parametrize("role", ["authors", "editors"])
def test_display_name_credits_with_distinct_separate_suffixes_are_not_duplicates(role):
    credits = (
        Contributor("John Smith", suffix="Jr"),
        Contributor("John Smith", suffix="Sr"),
    )
    original = BibliographicMetadata("Different credits", **{role: credits})

    update = metadata_values(original)
    restored = metadata_from_values(update.values)

    assert getattr(restored, role) == credits
    projected = getattr(metadata_bibliography_record(restored), role)
    assert [credit.family_name for credit in projected] == ["Smith Jr", "Smith Sr"]
    assert [credit.given_name for credit in projected] == ["John", "John"]
    with pytest.raises(MetadataValidationError, match="contributors must be unique"):
        metadata_values(replace(original, **{role: (credits[0], replace(credits[0], suffix="jr"))}))


@pytest.mark.parametrize("role", ["authors", "editors"])
def test_ambiguous_display_names_do_not_inherit_credit_attributes(role):
    original = _metadata()
    organization = replace(
        original.authors[0],
        display_name="World Health Organization",
        family_name=None,
        given_name=None,
        suffix=None,
        kind="organization",
        is_corresponding=None,
    )
    person = replace(
        organization, kind="person", family_name="Organization", given_name="World Health"
    )
    original = replace(original, **{role: (organization, person)})

    update = merge_metadata_values(
        original, {role: [{"display_name": organization.display_name}]}, merge=True
    )
    restored = metadata_from_values(metadata_values(original).values | update.values)

    assert getattr(restored, role) == (Contributor(organization.display_name),)


@pytest.mark.parametrize(
    "name_details",
    [
        {"kind": "person"},
        {"family_name": "Organization", "given_name": "World Health"},
        {"suffix": "Sr"},
    ],
)
def test_explicit_name_details_do_not_inherit_an_unrelated_organization(name_details):
    organization = Contributor(
        "World Health Organization", kind="organization", identifiers=(Identifier("isni", "123"),)
    )
    original = BibliographicMetadata("Organization credit", authors=(organization,))

    update = merge_metadata_values(
        original,
        {"authors": [{"display_name": organization.display_name, **name_details}]},
        merge=True,
    )
    credit = metadata_from_values(update.values).authors[0]

    assert credit.kind != "organization"
    assert credit.identifiers == ()


def test_inheriting_a_suffix_cannot_create_duplicate_credits():
    with pytest.raises(MetadataValidationError, match="contributors must be unique"):
        merge_metadata_values(
            _metadata(),
            {
                "authors": [
                    {"display_name": "John Smith"},
                    {
                        "display_name": "John Smith Jr",
                        "family_name": "Smith",
                        "given_name": "John",
                        "suffix": "Jr",
                    },
                ],
            },
            merge=True,
        )


@pytest.mark.parametrize("open_access", [None, False], ids=["unknown", "explicit-false"])
def test_link_merge_preserves_attributes_and_applies_known_access_status(open_access):
    original = _metadata()
    update = merge_metadata_values(
        original,
        {
            "urls": [
                {"url": "https://example.test/paper", "is_open_access": open_access},
                {"url": "https://example.test/landing", "kind": "landing_page"},
            ],
            "keywords": ["Graph; theory", "Robotics"],
        },
        merge=True,
    )
    restored = metadata_from_values(metadata_values(original).values | update.values)
    assert restored.urls[0] == replace(
        original.urls[0],
        is_open_access=open_access is None,
    )
    assert restored.urls[1].kind == "landing_page"
    assert restored.keywords == ("Graph; theory", "Robotics")


def test_manual_replacement_clears_optional_credit_attributes_and_links():
    update = metadata_values(
        BibliographicMetadata(
            "Replacement",
            authors=(Contributor("John Smith", family_name="Smith", given_name="John"),),
        )
    )
    restored = metadata_from_values(update.values)
    assert restored.authors[0].identifiers == () and restored.authors[0].affiliations is None
    assert restored.urls == () and update.identifiers == []


def test_url_duplicates_combine_descriptions_in_order_without_case_folding_paths():
    update = metadata_values(
        BibliographicMetadata(
            "Links",
            urls=(
                ResourceLink(" https://example.test/Paper ", media_type="application/pdf"),
                ResourceLink("https://example.test/Paper", license="cc-by", is_open_access=False),
                ResourceLink("https://example.test/paper", kind="landing_page"),
            ),
        )
    )
    restored = metadata_from_values(update.values)
    assert len(restored.urls) == 2
    assert restored.urls[0].media_type == "application/pdf"
    assert restored.urls[0].license == "cc-by" and restored.urls[0].is_open_access is False
    assert restored.urls[1].url == "https://example.test/paper"


def test_bibliography_projection_formats_suffixes_and_keeps_literal_contributors():
    projected = metadata_bibliography_record(_metadata())
    assert projected.authors[0].family_name == "Smith Jr"
    assert projected.editors[0].family_name == "Research Council"
    assert projected.editors[0].given_name is None
    assert projected.urls == ("https://example.test/paper",)
    assert dict(projected.identifiers) == {"openalex": "W123"}


@pytest.mark.parametrize(
    "record",
    [
        {"authors": "Smith"},
        {"urls": ["https://example.test"]},
        {"identifiers": '{"openalex":"W123"}'},
        {"identifiers": {"pmid": 123}},
    ],
)
def test_merge_rejects_delimiter_or_serialized_json_inputs(record):
    with pytest.raises(MetadataValidationError):
        merge_metadata_values(_metadata(), record, merge=True)


@pytest.mark.parametrize("value", ["doi:10.1000/EXAMPLE", "https://doi.org/10.1000/Example"])
def test_metadata_unifies_doi_inputs_with_the_same_canonical_value(value):
    update = metadata_values(
        BibliographicMetadata(
            title="Example", doi=value, identifiers=(Identifier("doi", "10.1000/example"),)
        )
    )
    assert update.identifiers == [("doi", "10.1000/example")]
    assert "doi" not in update.values


@pytest.mark.parametrize(
    "value, expected",
    [
        ("080442957x", "080442957X"),
        ("ISBN-10: 0-8044-2957-x", "080442957X"),
        ("urn:isbn:080442957X", "080442957X"),
        ("978-0-13-110362-7", "9780131103627"),
    ],
)
@pytest.mark.parametrize("source", [False, True], ids=["manual", "source"])
def test_metadata_normalizes_isbn_in_manual_and_source_identifiers(value, expected, source):
    if source:
        update = merge_metadata_values(
            BibliographicMetadata("ISBN"), {"identifiers": {"ISBN": value}}, merge=True
        )
    else:
        update = metadata_values(
            BibliographicMetadata("ISBN", identifiers=(Identifier("ISBN", value),))
        )

    assert update.identifiers == [("isbn", expected)]


@pytest.mark.parametrize("convert", ["manual", "candidate", "snapshot"])
def test_conflicting_doi_inputs_are_rejected(convert):
    def convert_conflicting_input():
        if convert == "manual":
            metadata_values(
                BibliographicMetadata(
                    title="Example",
                    doi="10.1000/first",
                    identifiers=(Identifier("doi", "10.1000/second"),),
                )
            )
        elif convert == "candidate":
            merge_metadata_values(
                BibliographicMetadata(title="Example"),
                {"doi": "10.1000/first", "identifiers": {"doi": "10.1000/second"}},
                merge=True,
            )
        else:
            metadata_from_values({
                "title": "Example",
                "doi": "10.1000/first",
                "identifiers": {"doi": "10.1000/second"},
            })

    with pytest.raises(MetadataValidationError, match="doi conflicts"):
        convert_conflicting_input()


def test_candidate_doi_is_derived_only_from_confirmed_identifiers():
    from dataclasses import asdict, fields

    record = CandidateRecord(
        provider="crossref", lookup_identifier=Identifier("doi", "10.1000/query"), title="Example"
    )
    assert record.doi is None
    record = replace(record, identifiers=(Identifier("doi", "10.1000/confirmed"),))
    assert record.doi == "10.1000/confirmed"
    assert "doi" not in asdict(record)
    assert "doi" not in {field.name for field in fields(CandidateRecord)}
