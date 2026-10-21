from __future__ import annotations

from uuid import uuid4

import httpx2
import pytest
from item_helpers import stored_doi, work_identifier
from provider_helpers import provider_runtime
from sqlalchemy import select
from workspace_helpers import provision_initial_workspace

from quirebase.library import (
    commit_import_batch,
    create_item,
    stage_identifiers_import_batch,
    sync_metadata_from_upstream,
)
from quirebase.models import AuditEvent, Item, User

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]
REQUEST_DOI = "10.1000/canonical"
RETURNED_DOI = "10.1000/Canonical"


@pytest.mark.parametrize(
    "published,expected",
    [
        ("2024-06-00", "2024-06"),
        ("2024-00-00", "2024"),
        ("2024-06-15T12:34:56Z", "2024-06-15T12:34:56Z"),
    ],
)
async def test_ads_provider_dates_remain_usable_for_import_and_sync(
    persistence_db, monkeypatch, published, expected
):
    from quirebase.core.config import get_settings

    db = persistence_db
    actor = User(username="provider-date-owner", password_hash="unused")
    db.add(actor)
    await db.flush()
    workspace = await provision_initial_workspace(db, actor)
    workspace_id = workspace.id
    await db.commit()
    bibcode = "2025ApJ...123..456A"

    def response(request):
        return httpx2.Response(
            200,
            json={
                "response": {
                    "docs": [{"bibcode": bibcode, "title": ["Provider date"], "pubdate": published}]
                }
            },
        )

    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda settings: provider_runtime(
            settings=settings, transport=httpx2.MockTransport(response)
        ),
    )
    settings = get_settings().model_copy(update={"nasa_ads_token": "ads-token"})
    batch = await stage_identifiers_import_batch(
        db, actor, workspace_id, [bibcode], provider="nasa_ads", settings=settings
    )
    assert batch.records[0].metadata.date_published == expected
    imported = (await commit_import_batch(db, actor, workspace_id, batch.id)).committed_item_ids
    assert (await db.get(Item, imported[0])).work["date_published"] == expected
    local = await create_item(
        db,
        actor,
        workspace_id,
        {"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Local"},
    )
    synced = await sync_metadata_from_upstream(
        db, actor, workspace_id, local.item_id, local.version, "nasa_ads", bibcode, settings
    )
    assert synced.work["date_published"] == expected
    assert synced.version == local.version + 1


@pytest.mark.parametrize(
    ("provider", "lookup_value"),
    [
        ("openalex", REQUEST_DOI),
        ("openalex", "W1220000000"),
        ("openalex", "https://openalex.org/W1220000000"),
        ("auto", REQUEST_DOI),
        ("crossref", REQUEST_DOI),
        ("datacite", REQUEST_DOI),
        ("commonmeta", REQUEST_DOI),
        ("commonmeta", f"https://doi.org/{REQUEST_DOI}"),
        ("pubmed", "https://pubmed.ncbi.nlm.nih.gov/42"),
        ("pubmed", "https://www.ncbi.nlm.nih.gov/pubmed/42/"),
    ],
)
@pytest.mark.parametrize("operation", ["import", "sync"])
async def test_provider_lookup_aliases_preserve_canonical_identifiers(
    persistence_db, monkeypatch, provider, lookup_value, operation
):
    db = persistence_db
    actor = User(username="provider-alias-owner", password_hash="unused")
    db.add(actor)
    await db.flush()
    workspace = await provision_initial_workspace(db, actor)
    workspace_id = workspace.id
    await db.commit()

    def response(request):
        if provider == "openalex":
            assert request.url.host == "api.openalex.org"
            payload = {
                "id": "https://openalex.org/W1230000000",
                "display_name": "Resolved Item",
                "doi": f"https://doi.org/{RETURNED_DOI}",
            }
        elif provider == "commonmeta":
            assert request.url.host == "commonmeta.org"
            assert request.url.params["format"] == "commonmeta"
            payload = {
                "id": f"https://doi.org/{RETURNED_DOI}",
                "type": "Dataset",
                "title": "Resolved Item",
            }
        elif provider == "pubmed":
            assert request.url.host == "eutils.ncbi.nlm.nih.gov"
            assert request.url.params["id"] == "42"
            return httpx2.Response(
                200,
                text=f'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article><ArticleTitle>Resolved Item</ArticleTitle></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">{RETURNED_DOI}</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>',
            )
        elif provider == "datacite":
            assert request.url.host == "api.datacite.org"
            payload = {
                "data": {
                    "attributes": {"doi": RETURNED_DOI, "titles": [{"title": "Resolved Item"}]}
                }
            }
        else:
            assert request.url.host == "api.crossref.org"
            payload = {"message": {"DOI": RETURNED_DOI, "title": ["Resolved Item"]}}
        return httpx2.Response(200, json=payload)

    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda settings: provider_runtime(
            settings=settings, transport=httpx2.MockTransport(response)
        ),
    )
    if operation == "import":
        batch = await stage_identifiers_import_batch(
            db, actor, workspace_id, [lookup_value], provider=provider
        )
        errors = batch.errors
        assert all(error.severity == "warning" for error in errors)
        assert batch.file_format == "metadata"
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "metadata.import.preview")
        )
        assert event.detail == {
            "requested": 1,
            "candidates": 1,
            "providers": ["crossref" if provider == "auto" else provider],
            "lookup_provider": provider,
        }
        await commit_import_batch(db, actor, workspace_id, batch.id)
        item = await db.scalar(select(Item).where(Item.workspace_id == workspace_id))
        assert item.version == 1
    else:
        original = await create_item(
            db,
            actor,
            workspace_id,
            {
                "id": f"urn:uuid:{uuid4()}",
                "type": "Document",
                "title": "Original",
                "identifiers": (work_identifier("arxiv", "2401.00001"),),
            },
        )
        item = await sync_metadata_from_upstream(
            db, actor, workspace_id, original.item_id, original.version, provider, lookup_value
        )
        assert item.version == 2
        event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "item.sync_upstream"))
        assert event.detail["provider"] == ("crossref" if provider == "auto" else provider)
        assert event.detail["lookup_provider"] == provider
    assert item.work.get("title") == "Resolved Item"
    assert stored_doi(item) == RETURNED_DOI.lower()
    expected = {"doi": RETURNED_DOI.lower()}
    if operation == "sync":
        expected["arxiv"] = "2401.00001"
    if provider == "openalex":
        expected["openalex"] = "W1230000000"
    if provider == "pubmed":
        expected["pmid"] = "42"
    from inquiro.work import work_identifiers

    assert dict(work_identifiers(item.work)) == expected
    assert item.workspace_id == workspace_id
