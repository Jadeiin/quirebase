from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from advanced_alchemy.types import FileObject
from inquiro import CandidateRecord, Identifier
from sqlalchemy import select
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.errors import VersionConflict
from quirebase.library import create_item, find_duplicates, revise_item_metadata, search_library
from quirebase.library.identifiers import rescan_pdf_doi, sync_metadata_from_upstream
from quirebase.models import AuditEvent, FileRevision, Item, User

pytestmark = pytest.mark.anyio


async def setup(db):
    actor = User(username="metadata-maintainer", password_hash="hash")
    db.add(actor)
    await db.flush()
    await provision_initial_workspace(db, actor)
    await db.commit()
    return actor, fixture_workspace_id(actor)


def metadata(title="Local", **fields):
    return {"id": f"urn:uuid:{uuid4()}", "type": "JournalArticle", "title": title, **fields}


async def test_pdf_scan_can_share_doi_and_keeps_manual_identifiers(persistence_db):
    db = persistence_db
    actor, workspace_id = await setup(db)
    await create_item(db, actor, workspace_id, metadata(id="https://doi.org/10.1234/scanned"))
    created = await create_item(
        db,
        actor,
        workspace_id,
        metadata(identifiers=[{"identifier_type": "PMID", "identifier": "42"}]),
    )
    db.add(
        FileRevision(
            workspace_id=workspace_id,
            item_id=created.item_id,
            full_text="doi: 10.1234/scanned",
            created_by=actor.id,
            file=FileObject(
                backend="documents",
                filename=str(uuid4()),
                size=1,
                content_type="application/pdf",
                metadata={"original_name": "paper.pdf"},
            ),
        )
    )
    await db.commit()
    assert await rescan_pdf_doi(db, actor, workspace_id, created.item_id) == "10.1234/scanned"
    item = await db.get(Item, created.item_id)
    assert item.work["identifiers"] == [
        {"identifier_type": "PMID", "identifier": "42"},
        {"identifier_type": "DOI", "identifier": "10.1234/scanned"},
    ]
    assert item.version == created.version + 1
    assert (await search_library(db, actor, workspace_id, q="scanned"))[1] == 2
    before = item.version
    assert await rescan_pdf_doi(db, actor, workspace_id, item.id) == "10.1234/scanned"
    assert item.version == before


async def test_provider_sync_allows_existing_identifiers_and_preserves_partial_facts(
    persistence_db, monkeypatch
):
    db = persistence_db
    actor, workspace_id = await setup(db)
    shared = "https://doi.org/10.1234/shared"
    await create_item(db, actor, workspace_id, metadata(id=shared))
    local = metadata(
        contributors=[
            {"type": "Organization", "organization": {"name": "Local Council"}, "roles": ["Author"]}
        ],
        subjects=[{"subject": "Local topic"}],
        relations=[{"id": "https://doi.org/10.1234/related", "type": "IsSupplementTo"}],
    )
    created = await create_item(db, actor, workspace_id, local, citation_key="ManualKey")

    async def lookup(*args, **kwargs):
        await asyncio.sleep(0)
        return CandidateRecord(
            "crossref",
            Identifier("doi", "10.1234/query"),
            metadata(
                "Provider", id=shared, identifiers=[{"identifier_type": "PMID", "identifier": "42"}]
            ),
        )

    monkeypatch.setattr("quirebase.library.identifiers.lookup_candidate", lookup)
    item = await sync_metadata_from_upstream(
        db, actor, workspace_id, created.item_id, created.version, "doi", "10.1234/query"
    )
    assert item.work["id"] == shared
    for key in ("contributors", "subjects", "relations"):
        assert item.work[key] == local[key]
    assert item.citation_key == "ManualKey"
    assert item.version == created.version + 1
    assert any(row.action == "item.sync_upstream" for row in await db.scalars(select(AuditEvent)))


async def test_provider_roundtrip_cannot_overwrite_concurrent_item_revision(
    async_db, async_session_factory, monkeypatch
):
    actor, workspace_id = await setup(async_db)
    actor_id = actor.id
    original = metadata()
    created = await create_item(async_db, actor, workspace_id, original)

    async def lookup(*args, **kwargs):
        async with async_session_factory() as other:
            writer = await other.get(User, actor_id)
            await revise_item_metadata(
                other,
                writer,
                workspace_id,
                created.item_id,
                created.version,
                original | {"title": "Concurrent edit"},
            )
        return CandidateRecord("crossref", Identifier("doi", "10.1234/query"), metadata("Provider"))

    monkeypatch.setattr("quirebase.library.identifiers.lookup_candidate", lookup)
    with pytest.raises(VersionConflict):
        await sync_metadata_from_upstream(
            async_db, actor, workspace_id, created.item_id, created.version, "doi", "10.1234/query"
        )
    assert (await async_db.get(Item, created.item_id)).work["title"] == "Concurrent edit"


async def test_provider_sync_retains_replaced_primary_identity_for_search_and_duplicates(
    persistence_db, monkeypatch
):
    from inquiro.work import work_identifiers

    db = persistence_db
    actor, workspace_id = await setup(db)
    primary = "https://openalex.org/W123"
    created = await create_item(
        db,
        actor,
        workspace_id,
        metadata(
            id=primary, identifiers=[{"identifier_type": "DOI", "identifier": "10.1234/synced"}]
        ),
    )

    async def lookup(*args, **kwargs):
        await asyncio.sleep(0)
        return CandidateRecord(
            "crossref",
            Identifier("doi", "10.1234/synced"),
            metadata("Synced", id="https://doi.org/10.1234/synced"),
        )

    monkeypatch.setattr("quirebase.library.identifiers.lookup_candidate", lookup)
    item = await sync_metadata_from_upstream(
        db, actor, workspace_id, created.item_id, created.version, "crossref", "10.1234/synced"
    )
    assert item.work["id"] == "https://doi.org/10.1234/synced"
    assert work_identifiers(item.work) == {("doi", "10.1234/synced"), ("openalex", "W123")}
    assert {"identifier_type": "OpenAlex", "identifier": primary} in item.work["identifiers"]
    assert (await search_library(db, actor, workspace_id, q="W123"))[1] == 1
    repeated = await sync_metadata_from_upstream(
        db, actor, workspace_id, item.id, item.version, "crossref", "10.1234/synced"
    )
    assert (
        repeated.work["identifiers"].count({"identifier_type": "OpenAlex", "identifier": primary})
        == 1
    )
    sibling = await create_item(db, actor, workspace_id, metadata("Sibling", id=primary))
    groups = await find_duplicates(db, actor, workspace_id, "identifier")
    assert [{row.id for row in group} for group in groups] == [{created.item_id, sibling.item_id}]
