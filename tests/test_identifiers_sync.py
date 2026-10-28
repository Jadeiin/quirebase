from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx2
import pytest
from inquiro import CandidateRecord, Identifier
from inquiro.work import contributor_name, work_authors
from provider_helpers import provider_runtime
from sqlalchemy import select
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.errors import VersionConflict
from quirebase.library import (
    LibraryFilter,
    create_item,
    find_duplicates,
    revise_item_metadata,
    search_library,
)
from quirebase.library.identifiers import sync_metadata_from_upstream
from quirebase.models import AuditEvent, Item, User

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


@pytest.mark.parametrize("include_orcids", [False, True])
async def test_crossref_openalex_sync_preserves_the_published_author_list(
    persistence_db, monkeypatch, include_orcids
):
    db = persistence_db
    actor, workspace_id = await setup(db)
    doi = "10.1016/j.conengprac.2024.105898"
    # Condensed from the Crossref and OpenAlex responses for this DOI. OpenAlex's
    # resolved author profile differs from the work's raw byline for Xiang Yu.
    authors = [
        ("Qianyuan", "Liu", None),
        ("Shangke", "Lyu", "0000-0002-8302-6630"),
        ("Kexin", "Guo", "0000-0002-0459-5027"),
        ("Jianliang", "Wang", "0000-0002-7265-4391"),
        ("Xiang", "Yu", "0000-0002-9005-3733"),
        ("Lei", "Guo", "0000-0002-3061-2337"),
    ]
    crossref = {
        "DOI": doi,
        "type": "journal-article",
        "title": [
            "A coordinated framework of aerial manipulator for safe and compliant physical interaction"
        ],
        "author": [
            {
                "given": given,
                "family": family,
                **({"ORCID": f"https://orcid.org/{orcid}"} if orcid else {}),
            }
            for given, family, orcid in authors
        ],
    }
    openalex = {
        "id": "https://openalex.org/W4392452505",
        "doi": f"https://doi.org/{doi}",
        "display_name": crossref["title"][0],
        "authorships": [
            {
                "raw_author_name": f"{given} {family}",
                "author": {
                    "display_name": "Xiang Yang Yu" if given == "Xiang" else f"{given} {family}",
                    **({"orcid": f"https://orcid.org/{orcid}"} if orcid else {}),
                },
                "institutions": [
                    {"display_name": "Beihang University", "ror": "https://ror.org/00wk2mp56"}
                ],
            }
            for given, family, orcid in authors
        ],
    }

    def response(request):
        payload = openalex if request.url.host == "api.openalex.org" else {"message": crossref}
        return httpx2.Response(200, json=payload)

    def runtime(settings=None):
        return provider_runtime(settings=settings, transport=httpx2.MockTransport(response))

    monkeypatch.setattr("quirebase.library.providers.provider_runtime", runtime)
    async with runtime() as source:
        local = (await source.lookup(doi, provider="crossref")).work
    if not include_orcids:
        for credit in local["contributors"]:
            credit["person"].pop("id", None)
    local["contributors"][4]["roles"].append("CorrespondingAuthor")
    local["contributors"][4]["person"]["affiliations"] = [{"name": "Local Institute"}]
    expected_names = [contributor_name(credit) for credit in work_authors(local)]
    created = await create_item(db, actor, workspace_id, local)
    version = created.version
    for provider in ("openalex", "openalex", "crossref"):
        item = await sync_metadata_from_upstream(
            db, actor, workspace_id, created.item_id, version, provider, doi
        )
        await db.refresh(item)
        credits = work_authors(item.work)
        assert [contributor_name(credit) for credit in credits] == expected_names
        assert credits[4]["person"]["id"] == "https://orcid.org/0000-0002-9005-3733"
        assert credits[4]["roles"] == ["Author", "CorrespondingAuthor"]
        assert credits[4]["person"]["affiliations"] == [
            {"name": "Local Institute"},
            {
                "name": "Beihang University",
                "identifier": "https://ror.org/00wk2mp56",
                "identifier_type": "ROR",
            },
        ]
        version += 1
        assert item.version == version


@pytest.mark.parametrize("starting_provider", ["crossref", "openalex"])
@pytest.mark.parametrize("include_orcids", [False, True])
async def test_provider_sync_matches_compound_surnames_without_changing_local_name_parts(
    persistence_db, monkeypatch, starting_provider, include_orcids
):
    db = persistence_db
    actor, workspace_id = await setup(db)
    doi = "10.1016/j.robot.2018.06.012"
    # Condensed from the published Crossref/OpenAlex responses. The first
    # author's complete name agrees, but the surname is split differently.
    authors = [
        ("Hossein", "Bonyan Khamseh", "0000-0002-1292-8987"),
        ("Farrokh", "Janabi-Sharifi", "0000-0002-0314-0688"),
        ("Abdelkader", "Abdessameud", "0000-0002-7294-6626"),
    ]
    crossref = {
        "DOI": doi,
        "type": "journal-article",
        "title": ["Aerial manipulation—A literature survey"],
        "author": [
            {
                "given": given,
                "family": family,
                **({"ORCID": f"https://orcid.org/{orcid}"} if index == 2 else {}),
            }
            for index, (given, family, orcid) in enumerate(authors)
        ],
    }
    openalex = {
        "id": "https://openalex.org/W2809971797",
        "doi": f"https://doi.org/{doi}",
        "display_name": crossref["title"][0],
        "authorships": [
            {
                "raw_author_name": f"{given} {family}",
                "author": {
                    "display_name": f"{given} {family}",
                    "orcid": f"https://orcid.org/{orcid}",
                },
                "institutions": [{"display_name": "Provider Institute"}],
            }
            for given, family, orcid in authors
        ],
    }

    def response(request):
        payload = openalex if request.url.host == "api.openalex.org" else {"message": crossref}
        return httpx2.Response(200, json=payload)

    def runtime(settings=None):
        return provider_runtime(settings=settings, transport=httpx2.MockTransport(response))

    monkeypatch.setattr("quirebase.library.providers.provider_runtime", runtime)
    async with runtime() as source:
        local = (await source.lookup(doi, provider=starting_provider)).work
    if not include_orcids:
        for credit in local["contributors"]:
            credit["person"].pop("id", None)
    first = local["contributors"][0]
    first["roles"].append("CorrespondingAuthor")
    first["person"]["affiliations"] = [{"name": "Local Institute"}]
    expected_names = [contributor_name(row) for row in local["contributors"]]
    expected_parts = [
        (row["person"].get("given_name"), row["person"].get("family_name"))
        for row in local["contributors"]
    ]
    created = await create_item(db, actor, workspace_id, local)
    version = created.version
    other_provider = "openalex" if starting_provider == "crossref" else "crossref"
    for provider in (other_provider, other_provider, starting_provider, "openalex"):
        item = await sync_metadata_from_upstream(
            db, actor, workspace_id, created.item_id, version, provider, doi
        )
        await db.refresh(item)
        credits = work_authors(item.work)
        assert [contributor_name(row) for row in credits] == expected_names
        assert [
            (row["person"].get("given_name"), row["person"].get("family_name")) for row in credits
        ] == expected_parts
        assert credits[0]["roles"] == ["Author", "CorrespondingAuthor"]
        assert {"name": "Local Institute"} in credits[0]["person"]["affiliations"]
        version += 1
        assert item.version == version
    assert [row["person"]["id"] for row in credits] == [
        f"https://orcid.org/{orcid}" for _, _, orcid in authors
    ]
    assert {"name": "Provider Institute"} in credits[0]["person"]["affiliations"]


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
    assert (await search_library(db, actor, workspace_id, LibraryFilter(q="W123")))[1] == 1
    repeated = await sync_metadata_from_upstream(
        db, actor, workspace_id, item.id, item.version, "crossref", "10.1234/synced"
    )
    assert (
        repeated.work["identifiers"].count({"identifier_type": "OpenAlex", "identifier": primary})
        == 1
    )
    sibling = await create_item(db, actor, workspace_id, metadata("Sibling", id=primary))
    groups = (await find_duplicates(db, actor, workspace_id, "identifier")).groups
    assert groups == []
    # Exact stored identifiers remain usable after sync, without comparing a
    # primary Work URI against an additional identifier of a different shape.
    matching = await create_item(
        db,
        actor,
        workspace_id,
        metadata(
            "Matching",
            identifiers=[{"identifier_type": "OpenAlex", "identifier": primary}],
        ),
    )
    groups = (await find_duplicates(db, actor, workspace_id, "identifier")).groups
    assert [{row.id for row in group} for group in groups] == [{created.item_id, matching.item_id}]
    assert (await db.get(Item, sibling.item_id)).work["id"] == primary
