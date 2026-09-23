from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx2
import pytest
from inquiro import CandidatePage, CandidateRecord, Identifier
from provider_helpers import provider_runtime
from sqlalchemy import select
from test_http import authenticated_async_client
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.config import get_settings
from quirebase.models import AuditEvent, Item, ItemIdentifier


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
        identifier=Identifier("openalex", "W99"),
        title="Candidate paper",
        authors="Researcher",
        publication_title="Journal",
        publication_date="2026",
    )
    monkeypatch.setattr(
        "quirebase.library.discovery.search_candidates",
        AsyncMock(return_value=CandidatePage("openalex", (result,), 11, 1, 10)),
    )
    try:
        searched = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/discovery/search",
            json={
                "provider": "openalex",
                "clauses": [{"operator": "and", "field": "title", "term": "quantum"}],
            },
        )
        assert searched.status_code == 200
        assert searched.json() == {
            "provider": "openalex",
            "results": [
                {
                    "provider": "openalex",
                    "identifier_provider": "openalex",
                    "identifier": "W99",
                    "title": "Candidate paper",
                    "authors": "Researcher",
                    "publication_title": "Journal",
                    "publication_date": "2026",
                    "doi": None,
                    "abstract": None,
                    "imported": False,
                }
            ],
            "total": 11,
            "page": 1,
            "per_page": 10,
        }
        event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "metadata.search"))
        assert event is not None
        assert json.loads(event.detail)["fields"] == ["title"]
        assert await db.scalar(select(AuditEvent).where(AuditEvent.action == "item.create")) is None
        assert (await db.scalars(select(Item.title))).all() == ["Paper"]
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_discovery_imported_check_queries_only_returned_identifiers(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    item.identifiers = "not valid JSON"
    async_db.add(ItemIdentifier(item_id=item.id, provider="openalex", value="W99"))
    await async_db.commit()
    result = CandidateRecord(
        provider="openalex",
        identifier=Identifier("openalex", "w99"),
        title="Already imported",
        doi="10.1000/candidate",
    )
    monkeypatch.setattr(
        "quirebase.library.discovery.search_candidates",
        AsyncMock(return_value=CandidatePage("openalex", (result,), 1, 1, 10)),
    )
    try:
        searched = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/discovery/search",
            json={
                "provider": "openalex",
                "clauses": [{"operator": "and", "field": "title", "term": "imported"}],
            },
        )

        assert searched.status_code == 200
        assert searched.json()["results"][0]["imported"] is True
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
    search_candidates = AsyncMock(return_value=CandidatePage("nasa", (), 0, 1, 10))
    monkeypatch.setattr("quirebase.library.discovery.search_candidates", search_candidates)
    try:
        providers = await client.get(f"/api/v1/workspaces/{item.workspace_id}/discovery/providers")
        searched = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/discovery/search",
            json={
                "provider": "nasa",
                "clauses": [{"operator": "and", "field": "any", "term": "stars"}],
            },
        )

        assert searched.status_code == 200
        assert {provider["id"] for provider in providers.json()} >= {"nasa", "openlibrary", "pmc"}
        assert search_candidates.await_args.args[1].nasa_ads_token == "runtime-token"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("year_from", "expected_error"),
    [
        ("not-a-year", "int_parsing"),
        ("999", "greater_than_equal"),
    ],
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
            json={
                "provider": "crossref",
                "clauses": [{"field": "title", "operator": "and", "term": "quantum"}],
                "year_from": year_from,
            },
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


@pytest.mark.anyio
async def test_discovery_search_preserves_sparse_condition_rows(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    search_candidates = AsyncMock(return_value=CandidatePage("openalex", (), 0, 1, 10))
    monkeypatch.setattr(
        "quirebase.library.discovery.search_candidates",
        search_candidates,
    )
    try:
        response = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/discovery/search",
            json={
                "provider": "openalex",
                "clauses": [
                    {"field": "title", "operator": "and", "term": "quantum"},
                    {"field": "author", "operator": "and", "term": ""},
                    {"field": "abstract", "operator": "not", "term": "review"},
                ],
            },
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
    from quirebase.library.imports import stage_identifier_import_batch
    from quirebase.models import User

    monkeypatch.setenv("INQUIRO_NASA_ADS_TOKEN", "ads-token")
    monkeypatch.setenv("INQUIRO_IEEE_API_KEY", "ieee-key")
    get_settings.cache_clear()

    def lookup_fallback_response(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.adsabs.harvard.edu":
            return httpx2.Response(
                200,
                json={
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
                },
            )
        if request.url.host == "ieeexploreapi.ieee.org":
            return httpx2.Response(
                200,
                json={
                    "articles": [
                        {
                            "title": "IEEE No-DOI result",
                            "article_number": "9876543",
                            "publication_title": "IEEE Journal",
                            "publication_year": "2025",
                            "authors": {"authors": [{"full_name": "Ieee Author"}]},
                        }
                    ]
                },
            )
        raise NotImplementedError(str(request.url))

    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda settings: provider_runtime(
            settings=settings,
            transport=httpx2.MockTransport(lookup_fallback_response),
        ),
    )

    db = async_db
    user = User(username="search_user", password_hash="unused")
    db.add(user)
    await db.flush()

    await provision_initial_workspace(db, user)
    await db.commit()

    batch_nasa, records_nasa, errors_nasa = await stage_identifier_import_batch(
        db,
        user,
        fixture_workspace_id(user),
        "2025ApJ...123..456A",
        "bibcode",
    )
    assert errors_nasa == []
    assert len(records_nasa) == 1
    assert batch_nasa.file_format == "metadata:bibcode"

    batch_ieee, records_ieee, errors_ieee = await stage_identifier_import_batch(
        db,
        user,
        fixture_workspace_id(user),
        "9876543",
        "article_number",
    )
    assert errors_ieee == []
    assert len(records_ieee) == 1
    assert batch_ieee.file_format == "metadata:article_number"
