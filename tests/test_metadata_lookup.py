import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app_helpers import json_payload
from commonmeta.author_utils import get_one_author
from commonmeta.base_utils import compact
from inquiro import (
    CandidateRecord,
    Identifier,
    LookupFailure,
    LookupOutcome,
    ProviderConfig,
    ProviderRuntime,
)
from inquiro.transport import MockExchange, TransportResponse
from item_helpers import stored_doi, work_identifier
from sqlalchemy import func, select
from test_http import authenticated_async_client

from quirebase.core.config import get_settings
from quirebase.library import stage_identifiers_import_batch
from quirebase.models import AuditEvent, ImportBatch, Item, ItemTagRecommendation


@pytest.mark.anyio
async def test_identifier_batch_with_provider_failure_rejects_pdf_retry(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, existing, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{existing.workspace_id}/imports"
    exchange = MockExchange(lambda _request: TransportResponse(503))
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )
    try:
        staged = await client.post(
            f"{base}/identifiers", json=json_payload({"identifiers": ["10.1000/unavailable"]})
        )
        assert staged.status_code == 201, staged.text
        preview = staged.json()
        assert preview["file_format"] == "metadata"
        assert preview["errors"][0]["code"] == "provider_unavailable"
        rejected = await client.post(f"{base}/{preview['id']}/retry", json=json_payload({}))
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["code"] == "import_batch_conflict"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_identifier_import_shares_one_runtime_for_native_and_singleton_requests(
    async_db, monkeypatch
):
    from urllib.parse import unquote

    from workspace_helpers import provision_initial_workspace

    from quirebase.models import User

    actor = User(username="batch-runtime", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    created = closed = 0

    def respond(request):
        if "ncbi" in request.url:
            assert request.params["id"] == "42,43"
            return TransportResponse(
                200,
                b"""<PubmedArticleSet>
              <PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
              <ArticleTitle>PubMed candidate</ArticleTitle>
              </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>""",
            )
        doi = unquote(request.url.rsplit("/", 1)[-1])
        assert "crossref" in request.url
        return TransportResponse(
            200,
            json.dumps({
                "message": {"DOI": doi, "title": [doi], "type": "journal-article"},
            }).encode(),
        )

    class RecordedExchange(MockExchange):
        async def aclose(self):
            nonlocal closed
            closed += 1

    exchange = RecordedExchange(respond)

    def runtime(_settings):
        nonlocal created
        created += 1
        return ProviderRuntime.with_exchange(ProviderConfig(), exchange)

    monkeypatch.setattr("quirebase.library.providers.provider_runtime", runtime)
    preview = await stage_identifiers_import_batch(
        async_db, actor, workspace.id, ["10.1234/one", "42", "43", "10.1234/two"]
    )
    assert created == closed == 1
    assert len(exchange.requests) == 3
    assert [record.metadata.title for record in preview.records] == [
        "10.1234/one",
        "PubMed candidate",
        "10.1234/two",
    ]
    assert [(error.row, error.identifier, error.code) for error in preview.errors] == [
        (3, "43", "metadata_not_found"),
    ]


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
        "quirebase.library.imports.lookup_candidates",
        AsyncMock(return_value=(LookupOutcome("10.1000/looked-up", record),)),
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
    source_work = {
        "id": f"urn:uuid:{uuid4()}",
        "type": "JournalArticle",
        "title": "Batch candidate",
        "identifiers": [
            work_identifier("doi", "10.1000/source-one"),
            work_identifier("doi", "10.1000/source-two"),
        ],
    }

    async def lookup(values, provider, _settings):
        assert provider == "auto"
        await asyncio.sleep(0)
        outcomes = []
        for value in values:
            if value == "invalid":
                result = LookupFailure("invalid_request", "unrecognized identifier")
            elif value == "10.1000/missing":
                result = LookupFailure("not_found", "metadata not found")
            elif value == "10.1000/down":
                result = LookupFailure("unavailable", "provider unavailable")
            else:
                work = {**source_work, "title": value}
                if value == "10.1000/bad-metadata":
                    work["title"] = "X" * 1001
                result = CandidateRecord(
                    "crossref",
                    Identifier("doi", value),
                    work,
                    diagnostics=("Partial provider fields",) if value == "42" else (),
                )
            outcomes.append(LookupOutcome(value, result))
        return tuple(outcomes)

    monkeypatch.setattr("quirebase.library.imports.lookup_candidates", lookup)
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
    monkeypatch.setattr("quirebase.library.imports.lookup_candidates", lookup)
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

    closed = asyncio.Event()

    async def lookup(_request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    class BlockingExchange(MockExchange):
        async def aclose(self):
            assert stopped.is_set()
            closed.set()

    exchange = BlockingExchange(lookup)
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )
    task = asyncio.create_task(
        stage_identifiers_import_batch(async_db, actor, workspace_id, ["42"])
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set() and closed.is_set()
    assert await async_db.scalar(select(func.count()).select_from(ImportBatch)) == 0
