import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app_helpers import json_payload
from commonmeta.author_utils import get_one_author
from commonmeta.base_utils import compact
from inquiro import CandidateRecord, Identifier
from item_helpers import stored_doi, work_identifier
from sqlalchemy import func, select
from test_http import authenticated_async_client

from quirebase.core.config import get_settings
from quirebase.core.errors import ResourceNotFound, UpstreamServiceError, ValidationFailure
from quirebase.library import stage_identifiers_import_batch
from quirebase.models import AuditEvent, ImportBatch, Item, ItemTagRecommendation


@pytest.mark.anyio
async def test_online_preview_uses_existing_confirmed_import_flow(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_id = item.workspace_id
    record = CandidateRecord(
        provider="crossref",
        lookup_identifier=Identifier("doi", "10.1000/looked-up"),
        work=compact({
            "id": f"urn:uuid:{uuid4()}",
            "type": "JournalArticle",
            "title": "Looked-up paper",
            "description": "Remote metadata",
            "date_published": "2026",
            "contributors": (get_one_author({"name": "Doe, Jane"}),),
            "container": {"title": "Journal"},
            "identifiers": [work_identifier("doi", "10.1000/looked-up")],
        }),
    )
    monkeypatch.setattr(
        "quirebase.library.imports.lookup_candidate", AsyncMock(return_value=record)
    )
    try:
        preview = await client.post(
            f"/api/v1/workspaces/{workspace_id}/imports/identifiers",
            json=json_payload({"identifiers": ["10.1000/looked-up"], "provider": "auto"}),
        )
        assert preview.status_code == 201
        assert "Looked-up paper" in preview.text
        assert (
            await db.scalar(select(Item).where(Item.work["title"].as_string() == "Looked-up paper"))
            is None
        )
        batch = await db.scalar(select(ImportBatch).where(ImportBatch.file_format == "metadata"))
        assert batch is not None
        batch_id = batch.id
        committed = await client.post(
            f"/api/v1/workspaces/{workspace_id}/imports/{batch_id}/commit", json=json_payload({})
        )
        assert committed.status_code == 200
        imported = await db.scalar(
            select(Item).where(Item.work["title"].as_string() == "Looked-up paper")
        )
        assert imported is not None
        assert stored_doi(imported) == "10.1000/looked-up"
        recommendation = await db.scalar(
            select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == imported.id)
        )
        assert recommendation is not None
        assert recommendation.workflow_id is not None
        assert await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "metadata.import.preview")
        )
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_identifier_batch_keeps_order_diagnostics_and_confirmation_boundary(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_id = item.workspace_id
    initial_count = await db.scalar(select(func.count()).select_from(Item))
    release_first = asyncio.Event()
    active = peak = 0
    completed = []
    source_work = {
        "id": f"urn:uuid:{uuid4()}",
        "type": "JournalArticle",
        "title": "Batch candidate",
        "identifiers": [
            work_identifier("doi", "10.1000/source-one"),
            work_identifier("doi", "10.1000/source-two"),
        ],
    }

    async def lookup(value, provider, _settings):
        nonlocal active, peak
        assert provider == "auto"
        active += 1
        peak = max(peak, active)
        try:
            if value == "10.1000/slow":
                await release_first.wait()
            else:
                await asyncio.sleep(0)
            if value == "42":
                release_first.set()
            if value == "invalid":
                raise ValidationFailure("unrecognized identifier")
            if value == "10.1000/missing":
                raise ResourceNotFound("metadata not found")
            if value == "10.1000/down":
                raise UpstreamServiceError("provider unavailable")
            work = {**source_work, "title": value}
            if value == "10.1000/bad-metadata":
                work["title"] = "X" * 1001
            return CandidateRecord(
                "crossref",
                Identifier("doi", value),
                work,
                diagnostics=("Partial provider fields",) if value == "42" else (),
            )
        finally:
            completed.append(value)
            active -= 1

    monkeypatch.setattr("quirebase.library.imports.lookup_candidate", lookup)
    try:
        preview = await client.post(
            f"/api/v1/workspaces/{workspace_id}/imports/identifiers",
            json={
                "identifiers": [
                    "10.1000/slow",
                    "invalid",
                    "42",
                    "10.1000/missing",
                    "10.1000/down",
                    "10.1000/bad-metadata",
                ]
            },
        )
        assert preview.status_code == 201, preview.text
        result = preview.json()
        assert [record["metadata"]["title"] for record in result["records"]] == [
            "10.1000/slow",
            "42",
        ]
        assert [(error["row"], error["code"]) for error in result["errors"]] == [
            (2, "invalid_identifier"),
            (3, "provider_limitations"),
            (4, "metadata_not_found"),
            (5, "provider_unavailable"),
            (6, "invalid_metadata"),
        ]
        assert result["errors"][0]["identifier"] == "invalid"
        assert completed.index("42") < completed.index("10.1000/slow")
        assert peak == 3 and active == 0
        assert await db.scalar(select(func.count()).select_from(Item)) == initial_count
        batch_id = result["id"]
        for _ in range(2):
            response = await client.post(
                f"/api/v1/workspaces/{workspace_id}/imports/{batch_id}/commit", json={}
            )
            assert response.status_code == 200, response.text
        assert await db.scalar(select(func.count()).select_from(Item)) == initial_count + 2
        imported = await db.scalar(select(Item).where(Item.work["title"].as_string() == "42"))
        assert imported.work["identifiers"] == source_work["identifiers"]
        assert imported.work["id"] == source_work["id"]
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
@pytest.mark.parametrize("identifiers", [[], ["42"] * 51, [""], ["X" * 501]])
async def test_identifier_api_rejects_unbounded_batches_before_lookup(
    async_db, async_session_factory, tmp_path, monkeypatch, identifiers
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    lookup = AsyncMock()
    monkeypatch.setattr("quirebase.library.imports.lookup_candidate", lookup)
    try:
        response = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/imports/identifiers",
            json={"identifiers": identifiers},
        )
        assert response.status_code == 422
        lookup.assert_not_awaited()
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_identifier_batch_cancellation_joins_provider_requests(async_db, monkeypatch):
    from workspace_helpers import provision_initial_workspace

    from quirebase.models import User

    actor = User(username="cancel-import", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    workspace_id = workspace.id
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def lookup(*_args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr("quirebase.library.imports.lookup_candidate", lookup)
    task = asyncio.create_task(
        stage_identifiers_import_batch(async_db, actor, workspace_id, ["42"])
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()
    assert await async_db.scalar(select(func.count()).select_from(ImportBatch)) == 0
