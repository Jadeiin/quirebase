from __future__ import annotations

import httpx2
import pytest
from provider_helpers import provider_runtime
from sqlalchemy import select
from workspace_helpers import provision_initial_workspace

from quirebase.library import (
    ExternalIdentifier,
    ItemMetadata,
    commit_import_batch,
    create_item,
    stage_identifier_import_batch,
    sync_metadata_from_upstream,
)
from quirebase.models import AuditEvent, Item, ItemIdentifier, User

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]

REQUEST_DOI = "10.1000/canonical"
RETURNED_DOI = "10.1000/Canonical"


@pytest.mark.parametrize(
    ("provider", "lookup_value"),
    [
        ("openalex", REQUEST_DOI),
        ("openalex", "W122"),
        ("auto", REQUEST_DOI),
        ("crossref", REQUEST_DOI),
        ("datacite", REQUEST_DOI),
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
                "id": "https://openalex.org/W123",
                "display_name": "Resolved Item",
                "doi": f"https://doi.org/{RETURNED_DOI}",
            }
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
        batch, _records, errors = await stage_identifier_import_batch(
            db, actor, workspace_id, lookup_value, provider=provider
        )
        assert errors == []
        assert batch.file_format == "metadata"
        event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "metadata.lookup"))
        assert event.detail == {
            "provider": "crossref" if provider == "auto" else provider,
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
            ItemMetadata(
                title="Original",
                identifiers=(ExternalIdentifier("arxiv", "2401.00001"),),
            ),
        )
        item = await sync_metadata_from_upstream(
            db, actor, workspace_id, original.item_id, original.version, provider, lookup_value
        )
        assert item.version == 2
        event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "item.sync_upstream"))
        assert event.detail["provider"] == ("crossref" if provider == "auto" else provider)
        assert event.detail["lookup_provider"] == provider

    assert item.title == "Resolved Item"
    assert item.doi == RETURNED_DOI
    expected = {"arxiv": "2401.00001"} if operation == "sync" else {}
    if provider == "openalex":
        expected["openalex"] = "W123"
    rows = (await db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item.id))).all()
    assert {row.provider: row.value for row in rows} == expected
    assert all(row.workspace_id == workspace_id for row in rows)
