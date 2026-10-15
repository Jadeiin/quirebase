from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from inquiro import CandidateRecord, Identifier, ProviderConfig, ProviderRuntime
from inquiro.transport import MockExchange, TransportResponse
from item_helpers import contributor
from workspace_helpers import provision_initial_workspace

from quirebase.library import (
    commit_import_batch,
    create_item,
    search_library,
    stage_identifiers_import_batch,
    sync_metadata_from_upstream,
)
from quirebase.models import ImportBatch, Item, User

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


async def owner(db):
    actor = User(username="structured-metadata", password_hash="unused")
    db.add(actor)
    await db.flush()
    workspace = await provision_initial_workspace(db, actor)
    await db.commit()
    return actor, workspace.id


async def test_import_preserves_complete_work_in_preview_and_confirmation(
    persistence_db, monkeypatch
):
    db = persistence_db
    actor, workspace_id = await owner(db)
    person = contributor("de la Cruz", "Juan", True)
    person["person"].update({
        "id": "https://orcid.org/0000-0002-1825-0097",
        "affiliations": [
            {
                "name": "University",
                "identifier_type": "ROR",
                "identifier": "https://ror.org/03yrm5c26",
            }
        ],
    })
    work = {
        "id": "https://openalex.org/W123",
        "type": "Dataset",
        "title": "Structured import",
        "contributors": [
            {
                "type": "Organization",
                "organization": {"name": "World Health Organization"},
                "roles": ["Author"],
            },
            person,
        ],
        "subjects": [{"subject": "Alpha; beta"}],
        "files": [{"url": "https://example.test/download", "mime_type": "application/pdf"}],
    }
    candidate = CandidateRecord("openalex", Identifier("openalex", "W123"), work)
    monkeypatch.setattr(
        "quirebase.library.imports.lookup_candidate", AsyncMock(return_value=candidate)
    )
    preview = await stage_identifiers_import_batch(db, actor, workspace_id, ["W123"], "openalex")
    assert preview.records[0].metadata.model_dump(mode="json") == work
    assert (await db.get(ImportBatch, preview.id)).records[0]["work"] == work
    ids = await commit_import_batch(db, actor, workspace_id, preview.id)
    db.expunge_all()
    assert (await db.get(Item, ids[0])).work == work


async def test_pubmed_suffixes_are_retained_in_standard_person_names(persistence_db, monkeypatch):
    db = persistence_db
    actor, workspace_id = await owner(db)
    xml = b"<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article><ArticleTitle>Distinct suffixes</ArticleTitle><AuthorList><Author><LastName>Smith</LastName><ForeName>John</ForeName><Suffix>Jr</Suffix></Author><Author><LastName>Smith</LastName><ForeName>John</ForeName><Suffix>Sr</Suffix></Author></AuthorList></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"

    async def lookup(value, provider, _settings):
        async with ProviderRuntime.with_exchange(
            ProviderConfig(), MockExchange(lambda _: TransportResponse(200, xml))
        ) as runtime:
            return await runtime.lookup(value, provider=provider)

    monkeypatch.setattr("quirebase.library.imports.lookup_candidate", lookup)
    preview = await stage_identifiers_import_batch(db, actor, workspace_id, ["42"], "pubmed")
    people = [credit.person for credit in preview.records[0].metadata.contributors]
    assert [person.name for person in people] == ["John Smith Jr", "John Smith Sr"]
    ids = await commit_import_batch(db, actor, workspace_id, preview.id)
    item = await db.get(Item, ids[0])
    assert [credit["person"]["name"] for credit in item.work["contributors"]] == [
        "John Smith Jr",
        "John Smith Sr",
    ]


@pytest.mark.parametrize("credits", [None], ids=["omitted"])
async def test_sync_distinguishes_missing_and_empty_contributor_lists(
    persistence_db, monkeypatch, credits
):
    db = persistence_db
    actor, workspace_id = await owner(db)
    work = {
        "id": f"urn:uuid:{uuid4()}",
        "type": "Document",
        "title": "Original",
        "contributors": [contributor("Lovelace", "Ada", True)],
    }
    created = await create_item(db, actor, workspace_id, work)
    incoming = {"id": work["id"], "type": "Document", "title": "Updated"}
    if credits is not None:
        incoming["contributors"] = credits
    record = CandidateRecord("openalex", Identifier("openalex", "W123"), incoming)
    monkeypatch.setattr(
        "quirebase.library.identifiers.lookup_candidate", AsyncMock(return_value=record)
    )
    item = await sync_metadata_from_upstream(
        db, actor, workspace_id, created.item_id, created.version, "openalex", "W123"
    )
    assert item.work.get("contributors", []) == (work["contributors"] if credits is None else [])
    assert (await search_library(db, actor, workspace_id, q="Lovelace"))[1] == (
        1 if credits is None else 0
    )


async def test_revision_updates_identifier_search_without_losing_hidden_facts(persistence_db):
    from quirebase.library import revise_item_metadata

    db = persistence_db
    actor, workspace_id = await owner(db)
    work = {
        "id": f"urn:uuid:{uuid4()}",
        "type": "Dataset",
        "title": "Snapshot",
        "contributors": [contributor("Smith", "Jane")],
        "identifiers": [{"identifier_type": "Other", "identifier": "oldmarker", "scheme": "local"}],
        "funding_references": [{"funder_name": "Foundation"}],
    }
    created = await create_item(db, actor, workspace_id, work)
    changed = deepcopy(work)
    changed["identifiers"][0]["identifier"] = "newmarker"
    await revise_item_metadata(db, actor, workspace_id, created.item_id, created.version, changed)
    assert (await db.get(Item, created.item_id)).work == changed
    assert (await search_library(db, actor, workspace_id, q="newmarker"))[1] == 1
    assert (await search_library(db, actor, workspace_id, q="oldmarker"))[1] == 0
