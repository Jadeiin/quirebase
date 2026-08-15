from __future__ import annotations

import json

import httpx
import pytest
from test_http import authenticated_client

from quirebase.core.config import Settings, get_settings
from quirebase.discovery import (
    MetadataLookupError,
    SearchClause,
    SearchPage,
    SearchResult,
    search_metadata,
)
from quirebase.models import AuditEvent
from quirebase.web.app import app


def search_response(request: httpx.Request) -> httpx.Response:
    if request.url.host == "api.crossref.org":
        return httpx.Response(
            200,
            json={
                "message": {
                    "total-results": 1,
                    "items": [
                        {
                            "DOI": "10.1/crossref",
                            "title": ["Crossref result"],
                            "author": [{"given": "Ada", "family": "Lovelace"}],
                            "container-title": ["Journal"],
                            "published": {"date-parts": [[2025]]},
                        }
                    ],
                }
            },
        )
    if request.url.host == "eutils.ncbi.nlm.nih.gov":
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"count": "1", "idlist": ["42"]}})
        return httpx.Response(
            200,
            json={
                "result": {
                    "42": {
                        "title": "PubMed result",
                        "authors": [{"name": "Medical Author"}],
                        "source": "Medical Journal",
                        "pubdate": "2024",
                    }
                }
            },
        )
    if request.url.host == "export.arxiv.org":
        return httpx.Response(
            200,
            text="""<feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
              <opensearch:totalResults>1</opensearch:totalResults><entry>
              <id>https://arxiv.org/abs/2601.00001</id><title>arXiv result</title>
              <summary>Preprint</summary><published>2026-01-01T00:00:00Z</published>
              <author><name>Preprint Author</name></author></entry></feed>""",
        )
    if request.url.host == "openlibrary.org":
        return httpx.Response(
            200,
            json={
                "numFound": 1,
                "docs": [
                    {
                        "title": "Book result",
                        "isbn": ["9780000000001"],
                        "author_name": ["Book Author"],
                        "publisher": ["Press"],
                        "first_publish_year": 2020,
                    }
                ],
            },
        )
    assert request.url.host == "api.openalex.org"
    assert request.url.params.get("api_key") == "test-key"
    if request.url.path == "/sources":
        return httpx.Response(
            200,
            json={"results": [{"id": "https://openalex.org/S123"}]},
        )
    if request.url.params.get("filter", "").startswith("title.search:"):
        assert "raw_author_name.search:!Example" in request.url.params["filter"]
    return httpx.Response(
        200,
        json={
            "meta": {"count": 1},
            "results": [
                {
                    "id": "https://openalex.org/W99",
                    "display_name": "OpenAlex result",
                    "doi": "https://doi.org/10.1/openalex",
                    "publication_date": "2026-02-01",
                    "type": "article",
                    "authorships": [{"author": {"display_name": "Open Author"}}],
                    "primary_location": {"source": {"display_name": "Open Journal"}},
                    "topics": [],
                }
            ],
        },
    )


@pytest.mark.parametrize(
    ("provider", "title"),
    [
        ("crossref", "Crossref result"),
        ("pubmed", "PubMed result"),
        ("arxiv", "arXiv result"),
        ("openlibrary", "Book result"),
        ("openalex", "OpenAlex result"),
    ],
)
def test_search_adapters_normalize_results(provider, title):
    page = search_metadata(
        provider,
        [
            SearchClause("title", "and", "machine learning"),
            SearchClause("author", "not", "Example"),
        ],
        page=1,
        sort="published",
        year_from=2020,
        year_to=2026,
        settings=Settings(openalex_api_key="test-key"),
        transport=httpx.MockTransport(search_response),
    )
    assert page.total == 1
    assert page.results[0].title == title
    assert page.results[0].identifier


def test_online_search_page_keeps_search_separate_from_import(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    result = SearchResult(
        provider="openalex",
        identifier_provider="openalex",
        identifier="W99",
        title="Candidate paper",
        authors="Researcher",
        publication_title="Journal",
        publication_date="2026",
    )
    monkeypatch.setattr(
        "quirebase.web.views.discovery.search_metadata",
        lambda *_args, **_kwargs: SearchPage("openalex", [result], 11, 1, 10),
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
        assert 'action="/metadata/preview?csrf_token=test-csrf"' in searched.text
        assert 'name="identifier" value="W99"' in searched.text
        event = db.query(AuditEvent).filter_by(action="metadata.search").one()
        assert json.loads(event.detail)["fields"] == ["title"]
        assert item.title not in searched.text
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_search_rejects_invalid_or_excessive_clauses():
    with pytest.raises(ValueError, match="unknown search provider"):
        search_metadata("other", [SearchClause("any", "and", "term")])
    with pytest.raises(ValueError, match="one to five"):
        search_metadata("openalex", [SearchClause("any", "and", "term")] * 6)
    with pytest.raises(ValueError, match="clause is invalid"):
        search_metadata("openalex", [SearchClause("private-field", "and", "term")])
    with pytest.raises(ValueError, match="only supports OR"):
        search_metadata(
            "openalex",
            [
                SearchClause("title", "and", "term"),
                SearchClause("author", "or", "person"),
            ],
        )


def test_openalex_resolves_publication_names_to_source_ids():
    page = search_metadata(
        "openalex",
        [SearchClause("publication", "and", "Journal")],
        settings=Settings(openalex_api_key="test-key"),
        transport=httpx.MockTransport(search_response),
    )
    assert page.results[0].title == "OpenAlex result"


def test_openalex_supports_adjacent_or_on_same_field():
    seen_filter = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_filter
        seen_filter = request.url.params.get("filter")
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})

    search_metadata(
        "openalex",
        [
            SearchClause("title", "and", "quantum"),
            SearchClause("title", "or", "photonics"),
        ],
        transport=httpx.MockTransport(handler),
    )

    assert seen_filter == "title.search:quantum|photonics"


def test_search_validation_and_pagination_are_bounded():
    with pytest.raises(ValueError, match="clause is invalid"):
        search_metadata("crossref", [SearchClause("any", "and", " ")])
    with pytest.raises(ValueError, match="clause is invalid"):
        search_metadata("crossref", [SearchClause("any", "and", "x" * 301)])
    with pytest.raises(ValueError, match="must not be after"):
        search_metadata(
            "crossref",
            [SearchClause("any", "and", "term")],
            year_from=2026,
            year_to=2020,
        )

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.url.params)
        return httpx.Response(200, json={"message": {"total-results": 0, "items": []}})

    page = search_metadata(
        "crossref",
        [SearchClause("any", "and", "term")],
        page=999,
        per_page=999,
        transport=httpx.MockTransport(handler),
    )
    assert page.page == 100
    assert page.per_page == 25
    assert captured["offset"] == "2475"
    assert captured["rows"] == "25"


def test_openlibrary_preserves_boolean_and_year_filters():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.url.params)
        return httpx.Response(200, json={"numFound": 0, "docs": []})

    search_metadata(
        "openlibrary",
        [
            SearchClause("title", "and", "distributed systems"),
            SearchClause("author", "or", "Tanenbaum"),
        ],
        year_from=2010,
        year_to=2020,
        transport=httpx.MockTransport(handler),
    )

    assert captured["q"] == 'title:"distributed systems" OR author:"Tanenbaum"'
    assert captured["first_publish_year"] == "[2010 TO 2020]"


def test_search_page_preserves_sparse_condition_rows(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    monkeypatch.setattr(
        "quirebase.web.views.discovery.search_metadata",
        lambda *_args, **_kwargs: SearchPage("openalex", [], 0, 1, 10),
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


def extra_search_response(request: httpx.Request) -> httpx.Response:
    if request.url.host == "eutils.ncbi.nlm.nih.gov":
        if request.url.path.endswith("esearch.fcgi"):
            assert request.url.params.get("db") == "pmc"
            return httpx.Response(200, json={"esearchresult": {"count": "1", "idlist": ["PMC123"]}})
        assert request.url.params.get("db") == "pmc"
        return httpx.Response(
            200,
            json={
                "result": {
                    "PMC123": {
                        "title": "PMC result",
                        "authors": [{"name": "Open Author"}],
                        "source": "PMC Journal",
                        "pubdate": "2025",
                        "articleids": [{"idtype": "doi", "value": "10.1/pmc"}],
                    }
                }
            },
        )
    if request.url.host == "api.adsabs.harvard.edu":
        assert request.headers["Authorization"] == "Bearer ads-token"
        return httpx.Response(
            200,
            json={
                "response": {
                    "numFound": 1,
                    "docs": [
                        {
                            "bibcode": "2025ApJ...1",
                            "title": ["NASA ADS result"],
                            "author": ["Astro Author"],
                            "pub": "ApJ",
                            "pubdate": "2025-01-01",
                            "doi": ["10.1/nasa"],
                        }
                    ],
                }
            },
        )
    assert request.url.host == "ieeexploreapi.ieee.org"
    assert request.url.params.get("apikey") == "ieee-key"
    return httpx.Response(
        200,
        json={
            "total_records": 1,
            "articles": [
                {
                    "title": "IEEE result",
                    "doi": "10.1/ieee",
                    "publication_title": "IEEE Journal",
                    "publication_year": 2025,
                    "authors": {"authors": [{"full_name": "Ieee Author"}]},
                }
            ],
        },
    )


@pytest.mark.parametrize(
    ("provider", "title", "identifier_provider"),
    [
        ("pmc", "PMC result", "doi"),
        ("nasa", "NASA ADS result", "doi"),
        ("ieee", "IEEE result", "doi"),
    ],
)
def test_extra_search_adapters_normalize_results(provider, title, identifier_provider):
    page = search_metadata(
        provider,
        [SearchClause("title", "and", "machine learning")],
        settings=Settings(nasa_ads_token="ads-token", ieee_api_key="ieee-key"),
        transport=httpx.MockTransport(extra_search_response),
    )
    assert page.total == 1
    assert page.results[0].title == title
    assert page.results[0].identifier_provider == identifier_provider


def test_credentialed_sources_require_keys():
    with pytest.raises(MetadataLookupError, match="QUIREBASE_NASA_ADS_TOKEN"):
        search_metadata(
            "nasa",
            [SearchClause("title", "and", "term")],
            transport=httpx.MockTransport(extra_search_response),
        )
    with pytest.raises(MetadataLookupError, match="QUIREBASE_IEEE_API_KEY"):
        search_metadata(
            "ieee",
            [SearchClause("title", "and", "term")],
            transport=httpx.MockTransport(extra_search_response),
        )
