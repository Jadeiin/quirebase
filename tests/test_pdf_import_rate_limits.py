from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pymupdf
import pytest
from inquiro import ProviderConfig, ProviderRuntime
from inquiro.transport import MockExchange, TransportResponse
from test_http import authenticated_async_client
from test_library_ui import finish_pdf_import_preview, pdf_bytes, published_pdf_bytes
from workspace_helpers import provision_initial_workspace

from quirebase.core.storage import get_object_store
from quirebase.library import (
    BatchConflict,
    get_import_batch_preview,
    retry_pdf_import_batch,
    stage_pdf_import_batch,
)
from quirebase.models import ImportBatch, User

pytestmark = pytest.mark.anyio


async def test_rejected_pdf_uploads_do_not_offer_retry(
    async_db, async_session_factory, monkeypatch
):
    actor = User(username=f"rejected-pdf-{uuid4().hex}", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    staged = await stage_pdf_import_batch(
        async_db, actor, workspace.id, [(b"not a PDF", "invalid.pdf")]
    )
    batch = await async_db.get(ImportBatch, staged.id)
    await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
    failed = await get_import_batch_preview(async_db, actor, workspace.id, batch.id)
    assert failed.status == "failed"
    assert not batch.staged_files
    assert [error.code for error in failed.errors] == ["invalid_pdf"]
    assert failed.can_retry is False
    with pytest.raises(BatchConflict):
        await retry_pdf_import_batch(async_db, actor, workspace.id, batch.id)


@pytest.mark.parametrize("recovered", [False, True])
async def test_zero_candidate_pdf_retries_replace_previous_source_diagnostics(
    async_db, async_session_factory, monkeypatch, recovered
):
    actor = User(username=f"invalid-metadata-retry-{uuid4().hex}", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    title = "x" * 1001

    def response(_request):
        return TransportResponse(
            200,
            json.dumps({
                "message": {
                    "DOI": "10.1000/retried",
                    "title": [title],
                    "type": "journal-article",
                }
            }).encode(),
        )

    exchange = MockExchange(response)
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )
    staged = await stage_pdf_import_batch(
        async_db,
        actor,
        workspace.id,
        [(published_pdf_bytes("10.1000/retried"), "retried.pdf")],
    )
    batch = await async_db.get(ImportBatch, staged.id)
    await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
    failed = await get_import_batch_preview(async_db, actor, workspace.id, batch.id)
    assert failed.status == "failed" and not failed.records
    assert failed.can_retry is True
    assert [error.code for error in failed.errors] == ["invalid_pdf"]
    source_id = failed.errors[0].source_id
    assert source_id is not None

    title = "Recovered metadata" if recovered else "y" * 1002
    await retry_pdf_import_batch(async_db, actor, workspace.id, batch.id)
    await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
    current = await get_import_batch_preview(async_db, actor, workspace.id, batch.id)
    assert len(exchange.requests) == 2
    if recovered:
        assert current.status == "ready"
        assert [record.metadata.title for record in current.records] == [title]
        assert current.records[0].source.id == source_id
        assert current.errors == ()
        assert current.can_retry is False
    else:
        assert current.status == "failed" and not current.records
        assert current.can_retry is True
        assert [(error.code, error.source_id) for error in current.errors] == [
            ("invalid_pdf", source_id)
        ]


async def test_metadata_retry_preserves_diagnostics_for_sources_not_retried(
    async_db, async_session_factory, monkeypatch
):
    actor = User(username=f"source-diagnostic-retry-{uuid4().hex}", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    recovered = False

    def response(_request):
        if not recovered:
            return TransportResponse(429, headers={"Retry-After": "3600"})
        return TransportResponse(
            200,
            json.dumps({
                "message": {
                    "DOI": "10.1000/deferred",
                    "title": ["Recovered metadata"],
                    "type": "journal-article",
                }
            }).encode(),
        )

    exchange = MockExchange(response)
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )
    staged = await stage_pdf_import_batch(
        async_db,
        actor,
        workspace.id,
        [
            (pdf_bytes(), "unidentified.pdf"),
            (published_pdf_bytes("10.1000/deferred"), "deferred.pdf"),
        ],
    )
    batch = await async_db.get(ImportBatch, staged.id)
    await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
    preview = await get_import_batch_preview(async_db, actor, workspace.id, batch.id)
    untouched = next(error for error in preview.errors if error.code == "missing_identifier")
    assert any(error.code == "provider_rate_limited" for error in preview.errors)
    assert preview.can_retry is True

    recovered = True
    await retry_pdf_import_batch(async_db, actor, workspace.id, batch.id)
    await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
    current = await get_import_batch_preview(async_db, actor, workspace.id, batch.id)
    assert current.status == "ready"
    assert current.can_retry is False
    assert current.errors == (untouched,)
    assert [record.source.id for record in current.records] == [
        record.source.id for record in preview.records
    ]
    assert len(exchange.requests) == 2


async def test_confirmation_rejects_a_preview_superseded_by_metadata_retry(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, existing, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    actor = await async_db.get(User, existing.created_by)
    workspace_id = existing.workspace_id
    base = f"/api/v1/workspaces/{workspace_id}"
    recovered = False

    def response(request):
        if "deferred" in request.url and not recovered:
            return TransportResponse(429, headers={"Retry-After": "3600"})
        return TransportResponse(
            200,
            json.dumps({
                "message": {
                    "DOI": "10.1000/confirmed",
                    "title": ["Confirmed metadata"],
                    "type": "journal-article",
                },
            }).encode(),
        )

    exchange = MockExchange(response)
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )
    try:
        staged = await stage_pdf_import_batch(
            async_db,
            actor,
            workspace_id,
            [
                (published_pdf_bytes("10.1000/ready"), "ready.pdf"),
                (published_pdf_bytes("10.1000/deferred"), "deferred.pdf"),
            ],
        )
        batch = await async_db.get(ImportBatch, staged.id)
        await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
        stale = (await client.get(f"{base}/imports/{batch.id}")).json()
        assert [record["is_basic"] for record in stale["records"]] == [False, True]
        recovered = True
        await retry_pdf_import_batch(async_db, actor, workspace_id, batch.id)
        await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
        current = (await client.get(f"{base}/imports/{batch.id}")).json()
        assert [record["is_basic"] for record in current["records"]] == [False, False]
        stale_selection = {
            "expected_preview_version": stale.get("preview_version"),
            "basic_source_ids": [],
        }
        rejected = await client.post(f"{base}/imports/{batch.id}/commit", json=stale_selection)
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["code"] == "import_batch_conflict"
        assert (await client.get(f"{base}/items")).json()["total"] == 1
        for file in batch.staged_files:
            assert await get_object_store().exists(file.path)
        for body in ({}, {"expected_preview_version": str(uuid4())}):
            assert (
                await client.post(f"{base}/imports/{batch.id}/commit", json=body)
            ).status_code == 409
        assert current["preview_version"] != stale["preview_version"]
        receipt = await client.post(
            f"{base}/imports/{batch.id}/commit",
            json={"expected_preview_version": current["preview_version"], "basic_source_ids": []},
        )
        assert receipt.status_code == 200, receipt.text
        assert len(receipt.json()["committed_item_ids"]) == 2
        replay = await client.post(f"{base}/imports/{batch.id}/commit", json=stale_selection)
        assert replay.json() == receipt.json()
        assert (await client.get(f"{base}/items")).json()["total"] == 3
    finally:
        await client.aclose()


def arxiv_pdf(identifier):
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((30, 700), f"arXiv:{identifier} [cs.RO] 1 Jun 2026", rotate=90)
        return document.tobytes()


def arxiv_response(identifiers):
    return TransportResponse(
        200,
        (
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            + "".join(
                f"<entry><id>https://arxiv.org/abs/{value}</id><title>Preprint {value}</title>"
                "<published>2026-06-01T00:00:00Z</published></entry>"
                for value in identifiers
            )
            + "</feed>"
        ).encode(),
    )


async def test_pdf_preparation_batches_arxiv_and_keeps_crossref_singleton(
    async_db, async_session_factory, monkeypatch
):
    actor = User(username=f"native-batch-{uuid4().hex}", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    values = [f"2606.{number:05d}v1" for number in range(1, 9)]
    uploads = [(arxiv_pdf(value), f"{index}.pdf") for index, value in enumerate(values)]
    uploads.insert(3, (published_pdf_bytes("10.1000/singleton"), "doi.pdf"))
    uploads.insert(7, (pdf_bytes(), "unidentified.pdf"))

    def response(request):
        if "arxiv" in request.url:
            assert request.params["id_list"] == ",".join(values)
            assert request.params["max_results"] == "8"
            return arxiv_response(reversed(values))
        assert request.url == "https://api.crossref.org/works/10.1000%2Fsingleton"
        return TransportResponse(
            200,
            json.dumps({
                "message": {
                    "DOI": "10.1000/singleton",
                    "title": ["Crossref singleton"],
                    "type": "journal-article",
                }
            }).encode(),
        )

    exchange = MockExchange(response)
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )
    staged = await stage_pdf_import_batch(async_db, actor, workspace.id, uploads)
    batch = await async_db.get(ImportBatch, staged.id)
    await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
    ready = await get_import_batch_preview(async_db, actor, workspace.id, batch.id)
    assert ready.status == "ready" and len(ready.records) == 10
    assert len(exchange.requests) == 2
    assert [row.source.original_name for row in ready.records] == [name for _, name in uploads]
    expected_titles = [f"Preprint {value}" for value in values]
    expected_titles.insert(3, "Crossref singleton")
    expected_titles.insert(7, "unidentified")
    assert [row.metadata.title for row in ready.records] == expected_titles
    assert [row.code for row in ready.errors] == ["missing_identifier"]
    for file in batch.staged_files:
        assert await get_object_store().exists(file.path)


async def test_pdf_duplicate_warnings_use_lookup_context_instead_of_returned_work_identity(
    async_db, async_session_factory, monkeypatch
):
    actor = User(username=f"lookup-context-{uuid4().hex}", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    exchange = MockExchange(
        lambda _request: TransportResponse(
            200,
            b'{"message":{"DOI":"10.1000/confirmed","title":["Same Work"],"type":"journal-article"}}',
        )
    )
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )
    staged = await stage_pdf_import_batch(
        async_db,
        actor,
        workspace.id,
        [
            (published_pdf_bytes("10.1000/first"), "first.pdf"),
            (published_pdf_bytes("10.1000/second"), "second.pdf"),
        ],
    )
    batch = await async_db.get(ImportBatch, staged.id)
    await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
    preview = await get_import_batch_preview(async_db, actor, workspace.id, batch.id)
    assert preview.status == "ready" and len(preview.records) == 2
    assert all(
        record.metadata.id == "https://doi.org/10.1000/confirmed" for record in preview.records
    )
    assert not preview.errors


async def test_native_pdf_batch_retries_only_failed_source_and_preserves_retry_after(
    async_db, async_session_factory, monkeypatch
):
    actor = User(username=f"partial-native-{uuid4().hex}", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    values = ["2606.00001v1", "2606.00002v1"]
    sleeps = AsyncMock()
    monkeypatch.setattr("quirebase.library.workflows.DBOS.sleep_async", sleeps)

    def response(request):
        if len(exchange.requests) == 1:
            body = arxiv_response(values).body
            return TransportResponse(
                200, body.replace(b"<title>Preprint 2606.00002v1</title>", b"")
            )
        assert request.params["id_list"] == values[1]
        if len(exchange.requests) == 2:
            return TransportResponse(429, headers={"Retry-After": "7"})
        return arxiv_response(values[1:])

    exchange = MockExchange(response)
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )
    staged = await stage_pdf_import_batch(
        async_db,
        actor,
        workspace.id,
        [(arxiv_pdf(value), "same.pdf") for value in values],
    )
    batch = await async_db.get(ImportBatch, staged.id)
    await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
    ready = await get_import_batch_preview(async_db, actor, workspace.id, batch.id)
    assert ready.status == "ready" and not ready.errors
    assert [row.metadata.title for row in ready.records] == [
        f"Preprint {value}" for value in values
    ]
    assert len(exchange.requests) == 3
    assert [call.args[0] for call in sleeps.await_args_list] == [5.0, 7.0]


async def test_rate_limited_pdf_keeps_successful_sibling_and_retains_both_files(
    async_db, async_session_factory, monkeypatch
):
    actor = User(username=f"rate-limit-{uuid4().hex}", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    sleeps = AsyncMock()
    monkeypatch.setattr("quirebase.library.workflows.DBOS.sleep_async", sleeps)

    def response(request):
        if "limited" in request.url:
            return TransportResponse(429, headers={"Retry-After": "7"})
        return TransportResponse(
            200,
            json.dumps({
                "message": {
                    "DOI": "10.1000/good",
                    "title": ["Successful sibling"],
                    "type": "journal-article",
                },
            }).encode(),
        )

    exchange = MockExchange(response)
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )
    staged = await stage_pdf_import_batch(
        async_db,
        actor,
        workspace.id,
        [
            (published_pdf_bytes("10.1000/limited"), "limited.pdf"),
            (published_pdf_bytes("10.1000/good"), "good.pdf"),
        ],
    )
    batch = await async_db.get(ImportBatch, staged.id)
    original_keys = [file.path for file in batch.staged_files]

    async def fail(batch_id, _workflow_id):
        async with async_session_factory() as db:
            failed = await db.get(ImportBatch, batch_id)
            failed.status = "failed"
            await db.commit()
        return True

    monkeypatch.setattr("quirebase.library.workflows.fail_pdf_import_batch_step", fail)
    await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
    preview = await get_import_batch_preview(async_db, actor, workspace.id, batch.id)
    assert preview.status == "ready"
    assert [(candidate.metadata.title, candidate.is_basic) for candidate in preview.records] == [
        ("limited", True),
        ("Successful sibling", False),
    ]
    assert [(error.filename, error.code) for error in preview.errors] == [
        ("limited.pdf", "provider_rate_limited"),
    ]
    # The successful sibling is checkpointed in the first group and is not retried.
    assert [request.url for request in exchange.requests].count(
        "https://api.crossref.org/works/10.1000%2Fgood"
    ) == 1
    assert sleeps.await_count == 2
    assert [call.args[0] for call in sleeps.await_args_list] == [7, 7]
    for key in original_keys:
        assert await get_object_store().exists(key)

    # Retry only the deferred source, retaining the successful sibling and source UUIDs.
    successful_work = preview.records[1].metadata.model_dump(mode="json")
    exchange.requests.clear()

    def available_response(_request):
        return TransportResponse(
            200,
            json.dumps({
                "message": {
                    "DOI": "10.1000/limited",
                    "title": ["Recovered metadata"],
                    "type": "journal-article",
                },
            }).encode(),
        )

    exchange.handler = available_response

    def unexpected_extraction(_path):
        raise AssertionError("retrying metadata must reuse the extracted lookup identifier")

    monkeypatch.setattr(
        "quirebase.library.imports.extract_pdf_lookup_identifier", unexpected_extraction
    )
    retried = await retry_pdf_import_batch(async_db, actor, workspace.id, batch.id)
    assert retried.status == "pending"
    await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
    recovered = await get_import_batch_preview(async_db, actor, workspace.id, batch.id)
    assert recovered.status == "ready"
    assert [candidate.metadata.title for candidate in recovered.records] == [
        "Recovered metadata",
        "Successful sibling",
    ]
    assert recovered.records[1].metadata.model_dump(mode="json") == successful_work
    assert not recovered.errors
    assert len(exchange.requests) == 1
    assert [candidate.source.id for candidate in recovered.records] == [
        candidate.source.id for candidate in preview.records
    ]


@pytest.mark.parametrize(
    "deferred_first",
    [False, True],
)
async def test_partial_metadata_retries_keep_duplicate_warnings_for_the_complete_batch(
    async_db, async_session_factory, monkeypatch, deferred_first
):
    actor = User(username=f"duplicate-retry-{uuid4().hex}", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    available = TransportResponse(
        200,
        json.dumps({
            "message": {
                "DOI": "10.1000/confirmed",
                "title": ["Confirmed metadata"],
                "type": "journal-article",
            },
        }).encode(),
    )
    deferred = TransportResponse(429, headers={"Retry-After": "3600"})
    responses = iter([
        deferred if deferred_first else available,
        available if deferred_first else deferred,
        deferred,
        available,
    ])
    exchange = MockExchange(lambda _request: next(responses))
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )
    staged = await stage_pdf_import_batch(
        async_db,
        actor,
        workspace.id,
        [
            (published_pdf_bytes("10.1000/SHARED"), "first.pdf"),
            (published_pdf_bytes("10.1000/shared"), "second.pdf"),
        ],
    )
    batch = await async_db.get(ImportBatch, staged.id)
    source_ids = None
    for preparation in range(3):
        if preparation:
            await retry_pdf_import_batch(async_db, actor, workspace.id, batch.id)
        await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
        preview = await get_import_batch_preview(async_db, actor, workspace.id, batch.id)
        assert preview.status == "ready"
        assert [record.source.original_name for record in preview.records] == [
            "first.pdf",
            "second.pdf",
        ]
        current_ids = [record.source.id for record in preview.records]
        if source_ids is None:
            source_ids = current_ids
        assert current_ids == source_ids
        assert [
            (error.row, error.filename)
            for error in preview.errors
            if error.code == "duplicate_batch_identifier"
        ] == [(2, "second.pdf")]
        if preparation < 2:
            assert sum(record.is_basic for record in preview.records) == 1
            assert sum(error.code == "provider_rate_limited" for error in preview.errors) == 1
        else:
            assert not any(record.is_basic for record in preview.records)
            assert [error.code for error in preview.errors] == ["duplicate_batch_identifier"]
            assert all(
                record.metadata.id == "https://doi.org/10.1000/confirmed"
                for record in preview.records
            )
    assert len(exchange.requests) == 4
    for file in batch.staged_files:
        assert await get_object_store().exists(file.path)


@pytest.mark.parametrize(
    "status,headers,requests,delays",
    [
        (429, {"Retry-After": "3600"}, 2, []),
        (503, {}, 6, [5.0, 10.0]),
    ],
)
async def test_provider_failure_wait_budget_retains_optional_pdfs_without_failing_the_batch(
    async_db, async_session_factory, monkeypatch, status, headers, requests, delays
):
    actor = User(username=f"bounded-backoff-{uuid4().hex}", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    sleeps = AsyncMock()
    monkeypatch.setattr("quirebase.library.workflows.DBOS.sleep_async", sleeps)
    exchange = MockExchange(lambda _: TransportResponse(status, headers=headers))
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )
    staged = await stage_pdf_import_batch(
        async_db,
        actor,
        workspace.id,
        [
            (published_pdf_bytes("10.1000/first"), "same.pdf"),
            (published_pdf_bytes("10.1000/second"), "same.pdf"),
        ],
    )
    batch = await async_db.get(ImportBatch, staged.id)
    await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
    preview = await get_import_batch_preview(async_db, actor, workspace.id, batch.id)
    assert preview.status == "ready" and len(preview.records) == 2
    assert all(candidate.is_basic for candidate in preview.records)
    assert [diagnostic.row for diagnostic in preview.errors] == [1, 2]
    assert [diagnostic.source_id for diagnostic in preview.errors] == [
        candidate.source.id for candidate in preview.records
    ]
    assert len(exchange.requests) == requests
    assert [call.args[0] for call in sleeps.await_args_list] == delays
    assert all(
        "identifiers" not in candidate.metadata.model_dump(exclude_none=True)
        for candidate in preview.records
    )
    for file in batch.staged_files:
        assert await get_object_store().exists(file.path)


async def test_authorization_is_rechecked_after_the_durable_rate_limit_wait(
    async_db, async_session_factory, monkeypatch
):
    actor = User(username=f"revoked-backoff-{uuid4().hex}", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    await async_db.commit()
    actor_id = actor.id
    exchange = MockExchange(lambda _: TransportResponse(429, headers={"Retry-After": "1"}))
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda _settings: ProviderRuntime.with_exchange(ProviderConfig(), exchange),
    )

    async def revoke(_seconds):
        async with async_session_factory() as db:
            persisted = await db.get(User, actor_id)
            persisted.active = False
            await db.commit()

    monkeypatch.setattr("quirebase.library.workflows.DBOS.sleep_async", revoke)
    staged = await stage_pdf_import_batch(
        async_db,
        actor,
        workspace.id,
        [
            (published_pdf_bytes("10.1000/revoked"), "revoked.pdf"),
        ],
    )
    batch = await async_db.get(ImportBatch, staged.id)
    await finish_pdf_import_preview(async_db, async_session_factory, batch, monkeypatch)
    assert batch.status == "failed"
    assert len(exchange.requests) == 1
    assert batch.errors[-1]["code"] == "authorization_revoked"
    for file in batch.staged_files:
        assert await get_object_store().exists(file.path)
