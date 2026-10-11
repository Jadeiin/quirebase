from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from inquiro import (
    Affiliation,
    CandidateRecord,
    Identifier,
    ProviderConfig,
    ProviderRuntime,
    ResourceLink,
)
from inquiro import Contributor as ProviderContributor
from inquiro.transport import MockExchange, TransportResponse
from item_helpers import contributor
from sqlalchemy import select
from workspace_helpers import provision_initial_workspace

from quirebase.library import (
    ItemMetadata,
    commit_import_batch,
    create_item,
    search_library,
    stage_identifier_import_batch,
    sync_metadata_from_upstream,
)
from quirebase.models import Item, User

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


async def _owner(db):
    actor = User(username="structured-metadata", password_hash="unused")
    db.add(actor)
    await db.flush()
    workspace = await provision_initial_workspace(db, actor)
    await db.commit()
    return actor, workspace.id


async def test_import_preserves_structured_preview_and_projects_names_without_reparsing(
    persistence_db, monkeypatch
):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    record = CandidateRecord(
        provider="openalex",
        lookup_identifier=Identifier("openalex", "W123"),
        title="Structured import",
        authors=(
            ProviderContributor("World Health Organization", kind="organization"),
            ProviderContributor(
                "Display name",
                family_name="de la Cruz",
                given_name="Juan",
                kind="person",
                identifiers=(Identifier("orcid", "0000-0002-1825-0097"),),
                affiliations=(
                    Affiliation(
                        "University",
                        (Identifier("ror", "https://ror.org/03yrm5c26"),),
                        raw_name="Research Lab, University",
                    ),
                ),
                is_corresponding=True,
            ),
        ),
        keywords=("Alpha; beta",),
        urls=(
            ResourceLink(
                "https://example.test/download",
                kind="full_text",
                media_type="application/pdf",
                license="cc-by",
                is_open_access=True,
            ),
        ),
        identifiers=(Identifier("openalex", "W123"),),
    )
    monkeypatch.setattr(
        "quirebase.library.imports.lookup_candidate", AsyncMock(return_value=record)
    )

    batch, _preview, errors = await stage_identifier_import_batch(
        db, actor, workspace_id, "W123", "openalex"
    )
    assert errors == []
    # Read the persisted JSON rather than only inspecting the in-memory value.
    await db.refresh(batch)
    staged = batch.records[0]
    assert staged["keywords"] == ["Alpha; beta"]
    assert staged["authors"][0]["display_name"] == "World Health Organization"
    assert staged["authors"][0]["family_name"] is None
    assert staged["authors"][1]["affiliations"][0]["identifiers"][0]["provider"] == "ror"
    assert staged["urls"][0]["media_type"] == "application/pdf"
    assert staged["urls"][0]["license"] == "cc-by"
    await commit_import_batch(db, actor, workspace_id, batch.id)
    item = await db.scalar(select(Item).where(Item.workspace_id == workspace_id))
    rows = [
        (row["family_name"], row["given_name"], row["is_corresponding"]) for row in item.authors
    ]
    assert rows == [(None, None, None), ("de la Cruz", "Juan", True)]
    assert item.keywords == ["Alpha; beta"]
    assert item.authors[1]["affiliations"][0]["name"] == "University"
    assert item.authors[1]["affiliations"][0]["raw_name"] == "Research Lab, University"
    assert item.authors[1]["affiliations"][0]["identifiers"] == [
        {"provider": "ror", "value": "https://ror.org/03yrm5c26"}
    ]
    assert item.authors[1]["identifiers"] == [{"provider": "orcid", "value": "0000-0002-1825-0097"}]
    assert item.urls[0]["url"] == "https://example.test/download"
    assert item.urls[0]["media_type"] == "application/pdf"
    assert item.urls[0]["license"] == "cc-by"
    assert item.urls[0]["is_open_access"] is True


async def test_pubmed_suffixes_survive_lookup_preview_and_import_confirmation(
    persistence_db, monkeypatch
):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    xml = b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
    <ArticleTitle>Distinct author suffixes</ArticleTitle><AuthorList>
    <Author><LastName>Smith</LastName><ForeName>John</ForeName><Suffix>Jr</Suffix></Author>
    <Author><LastName>Smith</LastName><ForeName>John</ForeName><Suffix>Sr</Suffix></Author>
    </AuthorList></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""

    async def lookup(value, provider, _settings):
        async with ProviderRuntime.with_exchange(
            ProviderConfig(), MockExchange(lambda _: TransportResponse(200, xml))
        ) as runtime:
            return await runtime.lookup(value, provider=provider)

    monkeypatch.setattr("quirebase.library.imports.lookup_candidate", lookup)
    batch, _preview, errors = await stage_identifier_import_batch(
        db, actor, workspace_id, "42", "pubmed"
    )
    assert errors == []
    await db.refresh(batch)
    authors = batch.records[0]["authors"]
    assert [author["family_name"] for author in authors] == ["Smith", "Smith"]
    assert [author["suffix"] for author in authors] == ["Jr", "Sr"]
    assert [author["display_name"] for author in authors] == ["John Smith Jr", "John Smith Sr"]

    await commit_import_batch(db, actor, workspace_id, batch.id)
    item = await db.scalar(select(Item).where(Item.workspace_id == workspace_id))
    names = [(row["family_name"], row["given_name"], row["suffix"]) for row in item.authors]
    assert names == [("Smith", "John", "Jr"), ("Smith", "John", "Sr")]


@pytest.mark.parametrize("flag", [None, False, True])
async def test_sync_preserves_unknown_corresponding_status_and_applies_explicit_values(
    persistence_db, monkeypatch, flag
):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    created = await create_item(
        db,
        actor,
        workspace_id,
        ItemMetadata("Original", authors=(contributor("Lovelace", "Ada", is_corresponding=True),)),
    )
    record = CandidateRecord(
        provider="openalex",
        lookup_identifier=Identifier("openalex", "W123"),
        title="Updated",
        authors=(
            ProviderContributor(
                "Ada Lovelace", family_name="Lovelace", given_name="Ada", is_corresponding=flag
            ),
        ),
    )
    monkeypatch.setattr(
        "quirebase.library.identifiers.lookup_candidate", AsyncMock(return_value=record)
    )
    await sync_metadata_from_upstream(
        db, actor, workspace_id, created.item_id, created.version, "openalex", "W123"
    )
    item = await db.get(Item, created.item_id)
    corresponding = item.authors[0]["is_corresponding"]
    assert corresponding is (True if flag is None else flag)


@pytest.mark.parametrize("authors", [None, ()], ids=["omitted", "clear"])
async def test_sync_distinguishes_missing_and_empty_contributor_lists(
    persistence_db, monkeypatch, authors
):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    created = await create_item(
        db,
        actor,
        workspace_id,
        ItemMetadata("Original", authors=(contributor("Lovelace", "Ada", True),)),
    )
    record = CandidateRecord(
        provider="openalex",
        lookup_identifier=Identifier("openalex", "W123"),
        title="Updated",
        authors=authors,
    )
    monkeypatch.setattr(
        "quirebase.library.identifiers.lookup_candidate", AsyncMock(return_value=record)
    )
    item = await sync_metadata_from_upstream(
        db, actor, workspace_id, created.item_id, created.version, "openalex", "W123"
    )
    await db.refresh(item)
    assert item.version == 2
    assert item.authors == (
        [
            {
                "display_name": "Lovelace, Ada",
                "family_name": "Lovelace",
                "given_name": "Ada",
                "is_corresponding": True,
            }
        ]
        if authors is None
        else []
    )
    assert (await search_library(db, actor, workspace_id, q="Lovelace"))[1] == (
        1 if authors is None else 0
    )


async def test_rich_metadata_revision_updates_loaded_identifiers_and_search_atomically(
    persistence_db,
):
    from dataclasses import replace

    from quirebase.library import ExternalIdentifier, revise_item_metadata
    from quirebase.models import ItemIdentifier

    db = persistence_db
    actor, workspace_id = await _owner(db)
    original = ItemMetadata(
        "Structured snapshot",
        authors=(
            ProviderContributor(
                "John Smith Jr",
                family_name="Smith",
                given_name="John",
                suffix="Jr",
                kind="person",
                is_corresponding=True,
                identifiers=(Identifier("orcid", "0000-0002-1825-0097"),),
                affiliations=(
                    Affiliation("University", identifiers=(Identifier("ror", "03yrm5c26"),)),
                ),
            ),
        ),
        editors=(ProviderContributor("Research Council", kind="organization"),),
        urls=(
            ResourceLink(
                "https://example.test/download",
                kind="full_text",
                media_type="application/pdf",
                license="cc-by",
                is_open_access=False,
            ),
        ),
        keywords=("Graph; theory",),
        identifiers=(ExternalIdentifier("pmid", "oldmarker"),),
    )
    result = await create_item(db, actor, workspace_id, original)
    item = await db.get(Item, result.item_id)
    await db.refresh(item, attribute_names=["identifier_links"])
    assert [row.value for row in item.identifier_links] == ["oldmarker"]
    assert (await search_library(db, actor, workspace_id, q="oldmarker"))[1] == 1
    updated = await revise_item_metadata(
        db,
        actor,
        workspace_id,
        item.id,
        result.version,
        replace(
            original,
            title="Revised snapshot",
            identifiers=(ExternalIdentifier("pmid", "newmarker"),),
        ),
    )
    assert updated.version == 2
    assert (await search_library(db, actor, workspace_id, q="newmarker"))[1] == 1
    assert (await search_library(db, actor, workspace_id, q="oldmarker"))[1] == 0
    assert (await search_library(db, actor, workspace_id, keyword_exact="Graph; theory"))[1] == 1
    assert item.authors[0]["identifiers"][0]["provider"] == "orcid"
    assert item.authors[0]["affiliations"][0]["identifiers"][0]["provider"] == "ror"
    assert item.urls[0]["is_open_access"] is False
    assert [row.value for row in item.identifier_links] == ["newmarker"]
    assert (
        await db.scalars(select(ItemIdentifier.value).where(ItemIdentifier.item_id == item.id))
    ).all() == ["newmarker"]


async def test_suffix_facets_and_exact_filters_preserve_distinct_names(persistence_db):
    from quirebase.library import LibraryFilter, get_library_facets, search_authors_typeahead

    db = persistence_db
    actor, workspace_id = await _owner(db)
    created = []
    for suffix in ("Jr", "Sr", None):
        name = " ".join(value for value in ("John Smith", suffix) if value)
        result = await create_item(
            db,
            actor,
            workspace_id,
            ItemMetadata(
                name,
                authors=(
                    ProviderContributor(
                        name, family_name="Smith", given_name="John", suffix=suffix
                    ),
                ),
            ),
        )
        created.append(result.item_id)
    literal = await create_item(
        db,
        actor,
        workspace_id,
        ItemMetadata(
            "Organization",
            authors=(
                ProviderContributor(
                    "Research Council",
                    family_name="Council",
                    given_name="Research",
                    kind="organization",
                ),
            ),
        ),
    )
    literal_items, literal_total = await search_library(
        db,
        actor,
        workspace_id,
        author_last_name="Research Council",
        author_first_name="",
    )
    assert literal_total == 1 and literal_items[0].id == literal.item_id
    facets = await get_library_facets(db, actor, workspace_id)
    assert {
        (row.last_name, row.first_name, row.suffix, row.item_count) for row in facets.authors
    } == {
        ("Smith", "John", "Jr", 1),
        ("Smith", "John", "Sr", 1),
        ("Smith", "John", None, 1),
        ("Research Council", None, None, 1),
    }
    for suffix, item_id in zip(("Jr", "Sr", ""), created, strict=True):
        rows, total = await search_library(
            db,
            actor,
            workspace_id,
            author_last_name="Smith",
            author_first_name="John",
            author_suffix=suffix,
        )
        assert total == 1 and rows[0].id == item_id
        filtered = await get_library_facets(
            db, actor, workspace_id, LibraryFilter(author_last_name="Smith", author_suffix=suffix)
        )
        assert len(filtered.authors) == 1
    assert (await search_library(db, actor, workspace_id, author="Smith Jr, John"))[1] == 1
    suggestions = await search_authors_typeahead(db, actor, workspace_id, "Smith")
    assert {row["full_name"] for row in suggestions} == {
        "Smith, John",
        "Smith Jr, John",
        "Smith Sr, John",
    }


async def test_exact_credit_filters_use_the_same_whitespace_rules_as_metadata_writes(
    persistence_db,
):
    db = persistence_db
    actor, workspace_id = await _owner(db)
    result = await create_item(
        db,
        actor,
        workspace_id,
        ItemMetadata(
            "Name spacing",
            authors=(
                ProviderContributor(
                    "John  Paul van   Helsing Jr",
                    family_name=" van   Helsing ",
                    given_name=" John  Paul ",
                    suffix=" Jr ",
                ),
            ),
        ),
    )
    rows, total = await search_library(
        db,
        actor,
        workspace_id,
        author_last_name=" van  Helsing ",
        author_first_name="John   Paul",
        author_suffix=" Jr ",
    )
    assert total == 1 and rows[0].id == result.item_id
    assert rows[0].authors[0]["display_name"] == "John Paul van Helsing Jr"
    assert rows[0].authors[0]["family_name"] == "van Helsing"
    assert rows[0].authors[0]["given_name"] == "John Paul"


async def test_cross_workspace_copy_preserves_rich_credits_and_links(persistence_db):
    from dataclasses import replace

    from quirebase.access import resolve_workspace_context
    from quirebase.library import (
        ExternalIdentifier,
        ItemSection,
        copy_item_to_workspace,
        open_item_section,
        revise_item_metadata,
    )
    from quirebase.models import ItemIdentifier, WorkspaceMember

    db = persistence_db
    actor, source_workspace_id = await _owner(db)
    target_owner = User(username="rich-copy-target", password_hash="unused")
    db.add(target_owner)
    await db.flush()
    target_workspace = await provision_initial_workspace(db, target_owner)
    db.add(WorkspaceMember(workspace_id=target_workspace.id, user_id=actor.id, role="editor"))
    await db.commit()
    original = ItemMetadata(
        "Rich copy",
        authors=(
            ProviderContributor(
                "Ada Lovelace",
                family_name="Lovelace",
                given_name="Ada",
                kind="person",
                identifiers=(Identifier("orcid", "0000-0002-1825-0097"),),
                affiliations=(Affiliation("University", country_code="GB"),),
            ),
        ),
        urls=(
            ResourceLink(
                "https://example.test/copy", kind="full_text", license="cc-by", is_open_access=False
            ),
        ),
        identifiers=(ExternalIdentifier("pmid", "copy-marker"),),
    )
    result = await create_item(db, actor, source_workspace_id, original)
    copied = await copy_item_to_workspace(
        db, actor, source_workspace_id, target_workspace.id, result.item_id
    )
    context = await resolve_workspace_context(db, actor, target_workspace.id)
    copied_view = await open_item_section(db, context, copied.id, ItemSection.metadata)
    assert copied_view.metadata == original
    assert (
        len(
            (
                await db.scalars(
                    select(ItemIdentifier).where(ItemIdentifier.value == "copy-marker")
                )
            ).all()
        )
        == 2
    )
    new_credit = replace(original.authors[0], affiliations=(Affiliation("Another university"),))
    await revise_item_metadata(
        db,
        actor,
        target_workspace.id,
        copied.id,
        copied.version,
        replace(original, authors=(new_credit,)),
    )
    source_context = await resolve_workspace_context(db, actor, source_workspace_id)
    source_view = await open_item_section(db, source_context, result.item_id, ItemSection.metadata)
    assert source_view.metadata == original
