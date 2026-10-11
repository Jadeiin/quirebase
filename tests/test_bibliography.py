import pytest
import rispy
from bibtexparser import parse_string as parse_bibtex_string
from inquiro.bibliography import (
    BibliographyExportOptions,
    Contributor,
    export_bibliography_records,
    parse_bibliography_records,
)
from item_helpers import bibliography_record_from_item as record_from_item
from item_helpers import contributor_values, metadata_list_values
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.library import (
    BatchConflict,
    commit_import_batch,
    export_accessible_bibliography,
    stage_import_batch,
)
from quirebase.models import CitationStyle, Item, ItemIdentifier, User


async def _user(db, username: str) -> User:
    user = User(username=username, password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.flush()
    return user


@pytest.mark.anyio
@pytest.mark.shared_postgres
@pytest.mark.parametrize("file_format", ["bibtex", "csl"])
@pytest.mark.parametrize("has_identifier", [False, True], ids=["no-identifiers", "with-doi"])
async def test_whole_workspace_export_loads_identifiers_in_a_fresh_session(
    persistence_db, file_format, has_identifier
):
    db = persistence_db
    owner = await _user(db, "fresh-export")
    workspace_id = fixture_workspace_id(owner)
    item = Item(
        workspace_id=workspace_id,
        created_by=owner.id,
        title="Fresh export",
        citation_key="fresh",
        identifier_links=[
            ItemIdentifier(workspace_id=workspace_id, provider="doi", value="10.1000/fresh")
        ]
        if has_identifier
        else [],
    )
    style = CitationStyle(
        workspace_id=workspace_id,
        created_by=owner.id,
        name="Export identifiers",
        csl_xml=(
            '<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0" class="in-text">'
            "<info><title>Export identifiers</title><id>https://example.test/style</id>"
            "<updated>2026-10-11T00:00:00+00:00</updated></info>"
            '<citation><layout><text variable="title"/></layout></citation>'
            '<bibliography><layout><group delimiter=" "><text variable="title"/>'
            '<text variable="DOI"/></group></layout></bibliography></style>'
        ),
    )
    db.add_all([item, style])
    await db.commit()

    async with AsyncSession(bind=db.bind, expire_on_commit=False) as request_db:
        request_user = await request_db.get(User, owner.id)
        assert request_user is not None
        contents, _media_type, _filename = await export_accessible_bibliography(
            request_db, request_user, workspace_id, file_format, style_key=str(style.id)
        )

    assert "Fresh export" in contents
    assert ("10.1000/fresh" in contents) is has_identifier


@pytest.mark.anyio
@pytest.mark.parametrize("valid_title", [True, False])
async def test_unknown_type_warning_allows_import_but_validation_errors_still_block(
    async_db, valid_title
):
    owner = await _user(async_db, "type-warning-owner")
    workspace_id = fixture_workspace_id(owner)
    title = "Preserved source type" if valid_title else ""
    batch = await stage_import_batch(
        async_db,
        owner,
        workspace_id,
        f"@unknown{{record, title = {{{title}}}}}".encode(),
        "bibtex",
    )
    records = batch.records
    diagnostics = batch.errors
    assert records[0].metadata.reference_type == "document"
    assert diagnostics[0].severity == "warning"
    if not valid_title:
        with pytest.raises(BatchConflict, match="preview contains errors"):
            await commit_import_batch(async_db, owner, workspace_id, batch.id)
        return
    item_ids = await commit_import_batch(async_db, owner, workspace_id, batch.id)
    item = await async_db.scalar(select(Item).where(Item.id == item_ids[0]))
    assert item.reference_type == "document"
    assert item.custom_fields["source_reference_type"] == "unknown"


def _item_payload(record):
    from inquiro.metadata import metadata_from_values, metadata_values, record_metadata_values

    from quirebase.models import ItemIdentifier

    metadata = metadata_from_values(record_metadata_values(record))
    return metadata_values(metadata).values | {
        "identifier_links": [
            ItemIdentifier(provider=row.provider, value=row.value) for row in metadata.identifiers
        ],
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
    assert records[0]["authors"] == contributor_values(
        "Doe, Jane; Smith, Alex", is_corresponding=None
    )
    user = await _user(db, "bibtex")
    item = Item(workspace_id=fixture_workspace_id(user), created_by=user.id, **records[0])
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
    assert stored["authors"] == contributor_values(
        "{World Health Organization}; de la Cruz Jr., Juan", is_corresponding=None
    )
    output = export_bibliography_records(records, "bibtex")
    round_trip, round_trip_errors = parse_bibliography_records(output, "bibtex")
    assert round_trip_errors == []
    assert round_trip[0].authors == records[0].authors


@pytest.mark.anyio
async def test_bibtex_export_can_protect_text_field_capitalization(async_db):
    db = async_db
    user = await _user(db, "bibtex-case")
    item = Item(
        title="An API for GraphQL and eBPF",
        workspace_id=fixture_workspace_id(user),
        abstract="Using CUDA with an LLM",
        authors=contributor_values("Doe, Jane; Smith, Alex", is_corresponding=None),
        keywords=metadata_list_values("API; GraphQL"),
        publication_title="Journal of eBPF Research",
        publisher="ACM Press",
        citation_key="case-protection",
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
    user = await _user(db, "duplicate-export-keys")
    first = Item(
        workspace_id=fixture_workspace_id(user),
        title="First",
        identifier_links=[],
        citation_key="SharedKey",
        created_by=user.id,
    )
    second = Item(
        workspace_id=fixture_workspace_id(user),
        title="Second",
        identifier_links=[],
        citation_key="sharedkey",
        created_by=user.id,
    )
    db.add_all([first, second])
    await db.commit()

    output = export_bibliography_records([record_from_item(i) for i in [first, second]], "bibtex")
    entries = parse_bibtex_string(output).entries_dict

    assert first.citation_key == "SharedKey"
    assert second.citation_key == "sharedkey"
    assert list(entries) == ["SharedKey", "sharedkeya"]


@pytest.mark.anyio
async def test_bibtex_case_protection_does_not_add_repeated_outer_braces(async_db):
    db = async_db
    user = await _user(db, "bibtex-braces")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="{Already Protected}",
        created_by=user.id,
    )

    protected = export_bibliography_records(
        [record_from_item(i) for i in [item]],
        "bibtex",
        options=BibliographyExportOptions(preserve_case=True),
    )

    assert "title = {{Already Protected}}" in protected


@pytest.mark.anyio
async def test_bibtex_case_protection_leaves_latex_commands_intact(async_db):
    db = async_db
    user = await _user(db, "bibtex-latex")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        title=r"Using \LaTeX with {CUDA}",
        created_by=user.id,
    )

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
        identifier_links=[
            ItemIdentifier(provider="openalex", value="W123"),
            ItemIdentifier(provider="arxiv", value="2401.00001"),
        ],
        custom_fields={
            "dataset_id": "DS-42",
            "Study Quality": "High",
            "study_quality": "Medium",
            "foo:bar": "Baz",
            "reviewed": True,
        },
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
    assert records[0]["custom_fields"] == {
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
    assert records[0]["authors"] == contributor_values(
        "Doe, Jane; Smith, Alex", is_corresponding=None
    )
    assert [(row.provider, row.value) for row in records[0]["identifier_links"]] == [
        ("doi", "10.1234/endnote")
    ]
    assert records[0]["reference_type"] == "article-journal"

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
