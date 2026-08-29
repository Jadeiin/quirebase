from __future__ import annotations

import json

import httpx2
import pytest
from inquiro import CandidatePage, CandidateRecord, Identifier
from provider_helpers import provider_runtime
from test_http import authenticated_client

from quirebase.core.config import get_settings
from quirebase.models import AuditEvent
from quirebase.web.app import app


def test_online_search_page_keeps_search_separate_from_import(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
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
        lambda *_args, **_kwargs: CandidatePage("openalex", (result,), 11, 1, 10),
    )
    try:
        empty = client.get("/online-search")
        assert empty.status_code == 200
        assert "联网检索" in empty.text
        assert "Candidate paper" not in empty.text

        searched = client.get(
            "/online-search",
            params=[
                ("provider", "openalex"),
                ("operator", "and"),
                ("field", "title"),
                ("term", "quantum"),
            ],
        )
        assert searched.status_code == 200
        assert "Candidate paper" in searched.text
        assert 'action="/metadata/preview"' in searched.text
        assert 'name="csrf_token" value="test-csrf"' in searched.text
        assert 'name="identifier" value="W99"' in searched.text
        event = db.query(AuditEvent).filter_by(action="metadata.search").one()
        assert json.loads(event.detail)["fields"] == ["title"]
        assert item.title not in searched.text
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("year_from", "expected_message"),
    [("not-a-year", "invalid literal"), ("999", "starting year is invalid")],
)
def test_online_search_page_renders_invalid_year_errors(
    db, tmp_path, monkeypatch, year_from, expected_message
):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        response = client.get(
            "/online-search",
            params={
                "provider": "crossref",
                "field": "title",
                "operator": "and",
                "term": "quantum",
                "year_from": year_from,
            },
        )

        assert response.status_code == 200
        assert expected_message in response.text
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_search_page_preserves_sparse_condition_rows(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    monkeypatch.setattr(
        "quirebase.library.discovery.search_candidates",
        lambda *_args, **_kwargs: CandidatePage("openalex", (), 0, 1, 10),
    )
    try:
        response = client.get(
            "/online-search",
            params=[
                ("field", "title"),
                ("field", "author"),
                ("field", "abstract"),
                ("operator", "and"),
                ("operator", "and"),
                ("operator", "not"),
                ("term", "quantum"),
                ("term", ""),
                ("term", "review"),
            ],
        )
        assert response.status_code == 200
        assert 'data-initial-clauses="3"' in response.text
        assert 'value="review"' in response.text
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_fallback_identifiers_can_be_staged_for_import(db, monkeypatch):
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

    user = User(username="search_user", password_hash="unused")
    db.add(user)
    db.flush()

    batch_nasa, records_nasa, errors_nasa = stage_identifier_import_batch(
        db,
        user,
        "2025ApJ...123..456A",
        "bibcode",
    )
    assert errors_nasa == []
    assert len(records_nasa) == 1
    assert batch_nasa.file_format == "metadata:bibcode"

    batch_ieee, records_ieee, errors_ieee = stage_identifier_import_batch(
        db,
        user,
        "9876543",
        "article_number",
    )
    assert errors_ieee == []
    assert len(records_ieee) == 1
    assert batch_ieee.file_format == "metadata:article_number"
