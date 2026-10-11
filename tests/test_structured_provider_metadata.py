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
from sqlalchemy import select
from workspace_helpers import provision_initial_workspace

from quirebase.library import (
    Contributor,
    ItemMetadata,
    commit_import_batch,
    create_item,
    stage_identifier_import_batch,
    sync_metadata_from_upstream,
)
from quirebase.models import Author, Item, ItemAuthor, User

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
    assert staged["authors"][0]["last_name"] == "World Health Organization"
    assert staged["authors"][0]["first_name"] is None
    assert staged["authors"][1]["affiliations"][0]["identifiers"][0]["provider"] == "ror"
    assert staged["urls"][0]["media_type"] == "application/pdf"
    assert staged["urls"][0]["license"] == "cc-by"
    await commit_import_batch(db, actor, workspace_id, batch.id)
    item = await db.scalar(select(Item).where(Item.workspace_id == workspace_id))
    rows = (
        await db.execute(
            select(Author.last_name, Author.first_name, ItemAuthor.is_corresponding)
            .join(ItemAuthor, ItemAuthor.author_id == Author.id)
            .where(ItemAuthor.item_id == item.id)
            .order_by(ItemAuthor.position)
        )
    ).all()
    assert rows == [("World Health Organization", None, False), ("de la Cruz", "Juan", True)]
    assert item.affiliation == "Research Lab, University"
    assert item.urls == "https://example.test/download"


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
    assert [author["last_name"] for author in authors] == ["Smith Jr", "Smith Sr"]

    await commit_import_batch(db, actor, workspace_id, batch.id)
    item = await db.scalar(select(Item).where(Item.workspace_id == workspace_id))
    names = (
        await db.execute(
            select(Author.last_name, Author.first_name)
            .join(ItemAuthor, ItemAuthor.author_id == Author.id)
            .where(ItemAuthor.item_id == item.id)
            .order_by(ItemAuthor.position)
        )
    ).all()
    assert names == [("Smith Jr", "John"), ("Smith Sr", "John")]


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
        ItemMetadata("Original", authors=(Contributor("Lovelace", "Ada", is_corresponding=True),)),
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
    corresponding = await db.scalar(
        select(ItemAuthor.is_corresponding).where(ItemAuthor.item_id == created.item_id)
    )
    assert corresponding is (True if flag is None else flag)
