from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from app_helpers import json_payload
from commonmeta.author_utils import get_one_author
from commonmeta.base_utils import compact
from inquiro import CandidatePage, CandidateRecord, Identifier
from item_helpers import work_identifier
from provider_helpers import provider_runtime
from sqlalchemy import event, select
from test_http import authenticated_async_client
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.config import get_settings
from quirebase.models import AuditEvent, Item


@pytest.mark.anyio
async def test_online_search_page_keeps_search_separate_from_import(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    result = CandidateRecord(
        provider="openalex",
        lookup_identifier=Identifier("openalex", "W9900000000"),
        work=compact({
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Candidate paper",
            "date_published": "2026",
            "contributors": (get_one_author({"name": "Researcher"}),),
            "container": {"title": "Journal"},
        }),
    )
    monkeypatch.setattr(
        "quirebase.library.discovery.search_candidates",
        AsyncMock(return_value=CandidatePage("openalex", (result,), 11, 1, 10)),
    )
    try:
        searched = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/discovery/search",
            json=json_payload({
                "provider": "openalex",
                "clauses": [{"operator": "and", "field": "title", "term": "quantum"}],
            }),
        )
        assert searched.status_code == 200
        assert searched.json() == {
            "provider": "openalex",
            "results": [
                {
                    "provider": "openalex",
                    "identifier_provider": "openalex",
                    "identifier": "W9900000000",
                    "title": "Candidate paper",
                    "authors": "Researcher",
                    "publication_title": "Journal",
                    "publication_date": "2026",
                    "doi": None,
                    "abstract": None,
                }
            ],
            "total": 11,
            "page": 1,
            "per_page": 10,
        }
        event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "metadata.search"))
        assert event is not None
        assert event.detail["fields"] == ["title"]
        assert await db.scalar(select(AuditEvent).where(AuditEvent.action == "item.create")) is None
        assert (await db.scalars(select(Item.work["title"].as_string()))).all() == ["Paper"]
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_discovery_does_not_read_stored_items_for_candidate_identity(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    item.work = {
        **item.work,
        "identifiers": [
            *item.work.get("identifiers", []),
            {"identifier_type": "OpenAlex", "identifier": "W9900000000"},
        ],
    }
    await async_db.commit()
    result = CandidateRecord(
        provider="openalex",
        lookup_identifier=Identifier("openalex", "w99"),
        work=compact({
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Already imported",
            "identifiers": [
                work_identifier("openalex", "W9900000000"),
                work_identifier("doi", "10.1000/candidate"),
            ],
        }),
    )
    monkeypatch.setattr(
        "quirebase.library.discovery.search_candidates",
        AsyncMock(return_value=CandidatePage("openalex", (result,), 1, 1, 10)),
    )
    item_reads = []
    engine = async_session_factory.kw["bind"].sync_engine

    def record_query(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select") and "from items" in statement.lower():
            item_reads.append(statement)

    event.listen(engine, "before_cursor_execute", record_query)
    try:
        searched = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/discovery/search",
            json=json_payload({
                "provider": "openalex",
                "clauses": [{"operator": "and", "field": "title", "term": "imported"}],
            }),
        )
        assert searched.status_code == 200
        assert "imported" not in searched.json()["results"][0]
        assert item_reads == []
    finally:
        event.remove(engine, "before_cursor_execute", record_query)
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "stored_isbn, candidate_isbn", [("080442957x", "080442957X"), ("080442957X", "080442957x")]
)
async def test_discovery_keeps_candidates_with_shared_isbn(
    async_db, async_session_factory, tmp_path, monkeypatch, stored_isbn, candidate_isbn
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    candidate = CandidateRecord(
        provider="openlibrary",
        lookup_identifier=Identifier("isbn", candidate_isbn),
        work=compact({
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "ISBN record",
            "identifiers": [work_identifier("isbn", candidate_isbn)],
        }),
    )
    monkeypatch.setattr(
        "quirebase.library.discovery.search_candidates",
        AsyncMock(return_value=CandidatePage("openlibrary", (candidate,), 1, 1, 10)),
    )
    try:
        created = await client.post(
            f"{workspace_base}/items",
            json={
                "metadata": {
                    "id": "urn:uuid:00000000-0000-4000-8000-000000000001",
                    "type": "Document",
                    "title": candidate.work.get("title"),
                    "identifiers": [{"identifier_type": "ISBN", "identifier": stored_isbn}],
                }
            },
        )
        assert created.status_code == 201
        searched = await client.post(
            f"{workspace_base}/discovery/search",
            json={
                "provider": "openlibrary",
                "clauses": [{"operator": "and", "field": "title", "term": "ISBN"}],
            },
        )
        assert searched.status_code == 200
        assert "imported" not in searched.json()["results"][0]
        from inquiro.work import work_identifiers

        created_item = await async_db.get(Item, __import__("uuid").UUID(created.json()["id"]))
        assert ("isbn", "080442957X") in work_identifiers(created_item.work)
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_discovery_search_uses_runtime_provider_settings(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    from quirebase.models import User
    from quirebase.operations.settings import update_runtime_settings

    admin = User(username="runtime_provider_admin", password_hash="unused", role="administrator")
    async_db.add(admin)
    await async_db.commit()
    await update_runtime_settings(async_db, admin, {"nasa_ads_token": "runtime-token"})
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    search_candidates = AsyncMock(return_value=CandidatePage("nasa_ads", (), 0, 1, 10))
    monkeypatch.setattr("quirebase.library.discovery.search_candidates", search_candidates)
    try:
        providers = await client.get(f"/api/v1/workspaces/{item.workspace_id}/discovery/providers")
        searched = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/discovery/search",
            json=json_payload({
                "provider": "nasa_ads",
                "clauses": [{"operator": "and", "field": "any", "term": "stars"}],
            }),
        )
        assert searched.status_code == 200
        assert providers.status_code == 200
        assert providers.json()["max_search_page_size"] == 100
        assert "max_search_page" not in providers.json()
        assert {provider["id"] for provider in providers.json()["search"]} >= {
            "nasa_ads",
            "openlibrary",
            "pmc",
        }
        assert "nasa_ads" in {provider["id"] for provider in providers.json()["lookup"]}
        assert "runtime-token" not in providers.text
        assert search_candidates.await_args.args[1].nasa_ads_token == "runtime-token"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_discovery_rejects_unsupported_sort_instead_of_silently_falling_back(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda settings: provider_runtime(
            settings=settings,
            transport=httpx2.MockTransport(
                lambda request: pytest.fail("unsupported sort must not make requests")
            ),
        ),
    )
    try:
        response = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/discovery/search",
            json={
                "provider": "arxiv",
                "sort": "cited",
                "clauses": [{"operator": "and", "field": "any", "term": "stars"}],
            },
        )
        assert response.status_code == 422
        assert response.json()["code"] == "validation_failed"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("year_from", "expected_error"), [("not-a-year", "int_parsing"), ("999", "greater_than_equal")]
)
@pytest.mark.anyio
async def test_discovery_search_rejects_invalid_years(
    async_db, async_session_factory, tmp_path, monkeypatch, year_from, expected_error
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/discovery/search",
            json=json_payload({
                "provider": "crossref",
                "clauses": [{"field": "title", "operator": "and", "term": "quantum"}],
                "year_from": year_from,
            }),
        )
        assert response.status_code == 422
        error = response.json()
        assert error["code"] == "validation_failed"
        assert error["fields"][0]["code"] == expected_error
        assert error["fields"][0]["path"] == ["body", "year_from"]
        assert "input" not in error["fields"][0]
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("clause", "path", "allowed"),
    [
        (
            {"field": "private", "operator": "and", "term": "quantum"},
            ["body", "clauses", 0, "field"],
            ("any", "title", "author", "publication", "abstract"),
        ),
        (
            {"field": "title", "operator": "contains", "term": "quantum"},
            ["body", "clauses", 0, "operator"],
            ("and", "or", "not"),
        ),
    ],
)
@pytest.mark.anyio
async def test_discovery_search_rejects_unknown_clause_values_before_calling_provider(
    async_db, async_session_factory, tmp_path, monkeypatch, clause, path, allowed
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    search_candidates = AsyncMock(side_effect=AssertionError("provider must not be called"))
    monkeypatch.setattr("quirebase.library.discovery.search_candidates", search_candidates)
    try:
        response = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/discovery/search",
            json=json_payload({"provider": "crossref", "clauses": [clause]}),
        )
        assert response.status_code == 422
        error = response.json()
        assert error["code"] == "validation_failed"
        (field_error,) = error["fields"]
        assert field_error["path"] == path
        assert field_error["code"] == "literal_error"
        assert all(value in field_error["message"] for value in allowed)
        search_candidates.assert_not_awaited()
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_discovery_search_preserves_sparse_condition_rows(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    search_candidates = AsyncMock(return_value=CandidatePage("openalex", (), 0, 1, 10))
    monkeypatch.setattr("quirebase.library.discovery.search_candidates", search_candidates)
    try:
        response = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/discovery/search",
            json=json_payload({
                "provider": "openalex",
                "clauses": [
                    {"field": "title", "operator": "and", "term": "quantum"},
                    {"field": "author", "operator": "and", "term": ""},
                    {"field": "abstract", "operator": "not", "term": "review"},
                ],
            }),
        )
        assert response.status_code == 200
        search = search_candidates.await_args.args[0]
        assert [(clause.field, clause.operator, clause.term) for clause in search.clauses] == [
            ("title", "and", "quantum"),
            ("author", "and", ""),
            ("abstract", "not", "review"),
        ]
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_fallback_identifiers_can_be_staged_for_import(async_db, monkeypatch):
    from quirebase.library.imports import stage_identifiers_import_batch
    from quirebase.models import User

    monkeypatch.setenv("INQUIRO_NASA_ADS_TOKEN", "ads-token")
    monkeypatch.setenv("INQUIRO_IEEE_API_KEY", "ieee-key")
    get_settings.cache_clear()

    def lookup_fallback_response(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.adsabs.harvard.edu":
            return httpx2.Response(
                200,
                json=json_payload({
                    "response": {
                        "docs": [
                            {
                                "bibcode": ["2025ApJ...123..456A"],
                                "title": ["NASA No-DOI result"],
                                "author": ["Astro Author"],
                                "pub": ["ApJ"],
                                "pubdate": ["2025-01-01"],
                            }
                        ]
                    }
                }),
            )
        if request.url.host == "ieeexploreapi.ieee.org":
            return httpx2.Response(
                200,
                json=json_payload({
                    "articles": [
                        {
                            "title": "IEEE No-DOI result",
                            "article_number": "9876543",
                            "publication_title": "IEEE Journal",
                            "publication_year": "2025",
                            "authors": {"authors": [{"full_name": "Ieee Author"}]},
                        }
                    ]
                }),
            )
        raise NotImplementedError(str(request.url))

    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda settings: provider_runtime(
            settings=settings, transport=httpx2.MockTransport(lookup_fallback_response)
        ),
    )
    db = async_db
    user = User(username="search_user", password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    batch_nasa = await stage_identifiers_import_batch(
        db, user, fixture_workspace_id(user), ["2025ApJ...123..456A"], "bibcode"
    )
    records_nasa = batch_nasa.records
    errors_nasa = batch_nasa.errors
    assert not errors_nasa
    assert len(records_nasa) == 1
    assert batch_nasa.file_format == "metadata"
    batch_ieee = await stage_identifiers_import_batch(
        db, user, fixture_workspace_id(user), ["9876543"], "ieee"
    )
    records_ieee = batch_ieee.records
    errors_ieee = batch_ieee.errors
    assert not errors_ieee
    assert len(records_ieee) == 1
    assert batch_ieee.file_format == "metadata"
