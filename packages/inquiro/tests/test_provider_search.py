from __future__ import annotations

from types import SimpleNamespace

import httpx2
import pytest
from inquiro import Identifier, ProviderUnavailable, SearchClause, SearchQuery
from inquiro_provider_helpers import provider_runtime


def search_metadata(
    provider,
    clauses,
    *,
    page=1,
    per_page=10,
    sort="relevance",
    year_from=None,
    year_to=None,
    settings=None,
    transport=None,
):
    transport = transport or httpx2.MockTransport(
        lambda request: (_ for _ in ()).throw(AssertionError(str(request.url)))
    )
    with provider_runtime(settings=settings, transport=transport) as runtime:
        return runtime.search(
            SearchQuery(
                provider=provider,
                clauses=tuple(clauses),
                page=page,
                per_page=per_page,
                sort=sort,
                year_from=year_from,
                year_to=year_to,
            )
        )


def search_response(request: httpx2.Request) -> httpx2.Response:
    if request.url.host == "api.crossref.org":
        return httpx2.Response(
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
            return httpx2.Response(200, json={"esearchresult": {"count": "1", "idlist": ["42"]}})
        return httpx2.Response(
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
        return httpx2.Response(
            200,
            text="""<feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
              <opensearch:totalResults>1</opensearch:totalResults><entry>
              <id>https://arxiv.org/abs/2601.00001</id><title>arXiv result</title>
              <summary>Preprint</summary><published>2026-01-01T00:00:00Z</published>
              <author><name>Preprint Author</name></author></entry></feed>""",
        )
    if request.url.host == "openlibrary.org":
        return httpx2.Response(
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
        return httpx2.Response(
            200,
            json={"results": [{"id": "https://openalex.org/S123"}]},
        )
    if request.url.params.get("filter", "").startswith("title.search:"):
        assert "raw_author_name.search:!Example" in request.url.params["filter"]
    return httpx2.Response(
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
        settings=SimpleNamespace(openalex_api_key="test-key"),
        transport=httpx2.MockTransport(search_response),
    )
    assert page.total == 1
    assert page.results[0].title == title
    assert page.results[0].identifier


def test_search_rejects_invalid_or_excessive_clauses():
    with pytest.raises(ValueError, match="unknown search provider"):
        search_metadata("other", [SearchClause("any", "and", "term")])
    with pytest.raises(ValueError, match="unknown search provider"):
        search_metadata("datacite", [SearchClause("any", "and", "term")])
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
        settings=SimpleNamespace(openalex_api_key="test-key"),
        transport=httpx2.MockTransport(search_response),
    )
    assert page.results[0].title == "OpenAlex result"


def test_openalex_supports_adjacent_or_on_same_field():
    seen_filter = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen_filter
        seen_filter = request.url.params.get("filter")
        return httpx2.Response(200, json={"meta": {"count": 0}, "results": []})

    search_metadata(
        "openalex",
        [
            SearchClause("title", "and", "quantum"),
            SearchClause("title", "or", "photonics"),
        ],
        transport=httpx2.MockTransport(handler),
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

    captured: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.update(request.url.params)
        return httpx2.Response(200, json={"message": {"total-results": 0, "items": []}})

    page = search_metadata(
        "crossref",
        [SearchClause("any", "and", "term")],
        page=999,
        per_page=999,
        transport=httpx2.MockTransport(handler),
    )
    assert page.page == 100
    assert page.per_page == 25
    assert captured["offset"] == "2475"
    assert captured["rows"] == "25"


def test_search_404_is_an_empty_page():
    page = search_metadata(
        "crossref",
        [SearchClause("any", "and", "missing")],
        transport=httpx2.MockTransport(lambda _request: httpx2.Response(404)),
    )

    assert page.provider == "crossref"
    assert page.results == ()
    assert page.total == 0


def test_openlibrary_preserves_boolean_and_year_filters():
    captured: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.update(request.url.params)
        return httpx2.Response(200, json={"numFound": 0, "docs": []})

    search_metadata(
        "openlibrary",
        [
            SearchClause("title", "and", "distributed systems"),
            SearchClause("author", "or", "Tanenbaum"),
        ],
        year_from=2010,
        year_to=2020,
        transport=httpx2.MockTransport(handler),
    )

    assert captured["q"] == 'title:"distributed systems" OR author:"Tanenbaum"'
    assert captured["first_publish_year"] == "[2010 TO 2020]"


def extra_search_response(request: httpx2.Request) -> httpx2.Response:
    if request.url.host == "eutils.ncbi.nlm.nih.gov":
        if request.url.path.endswith("esearch.fcgi"):
            assert request.url.params.get("db") == "pmc"
            return httpx2.Response(
                200, json={"esearchresult": {"count": "1", "idlist": ["PMC123"]}}
            )
        assert request.url.params.get("db") == "pmc"
        return httpx2.Response(
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
        return httpx2.Response(
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
    return httpx2.Response(
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
        settings=SimpleNamespace(nasa_ads_token="ads-token", ieee_api_key="ieee-key"),
        transport=httpx2.MockTransport(extra_search_response),
    )
    assert page.total == 1
    assert page.results[0].title == title
    assert page.results[0].identifier.provider == identifier_provider


def test_pmc_forwards_credentials_to_esearch_and_esummary():
    recorded_params = []

    def pmc_credential_response(request: httpx2.Request) -> httpx2.Response:
        recorded_params.append((request.url.path, dict(request.url.params)))
        if request.url.path.endswith("esearch.fcgi"):
            return httpx2.Response(
                200, json={"esearchresult": {"count": "1", "idlist": ["PMC999"]}}
            )
        return httpx2.Response(
            200,
            json={
                "result": {
                    "PMC999": {
                        "title": "PMC Credentialed result",
                        "authors": [{"name": "Auth"}],
                        "source": "PMC J",
                        "pubdate": "2025",
                        "articleids": [{"idtype": "doi", "value": "10.1/pmc999"}],
                    }
                }
            },
        )

    search_metadata(
        "pmc",
        [SearchClause("title", "and", "test")],
        settings=SimpleNamespace(
            metadata_contact_email="pmc@test.org", ncbi_api_key="ncbi-secret-key"
        ),
        transport=httpx2.MockTransport(pmc_credential_response),
    )
    assert len(recorded_params) == 2
    esearch_path, esearch_params = recorded_params[0]
    esummary_path, esummary_params = recorded_params[1]
    assert esearch_path.endswith("esearch.fcgi")
    assert esearch_params["email"] == "pmc@test.org"
    assert esearch_params["api_key"] == "ncbi-secret-key"
    assert esummary_path.endswith("esummary.fcgi")
    assert esummary_params["email"] == "pmc@test.org"
    assert esummary_params["api_key"] == "ncbi-secret-key"


def test_credentialed_sources_require_keys():
    with pytest.raises(ProviderUnavailable) as nasa_error:
        search_metadata(
            "nasa",
            [SearchClause("title", "and", "term")],
            transport=httpx2.MockTransport(extra_search_response),
        )
    assert str(nasa_error.value) == "NASA ADS requires QUIREBASE_NASA_ADS_TOKEN"

    with pytest.raises(ProviderUnavailable) as ieee_error:
        search_metadata(
            "ieee",
            [SearchClause("title", "and", "term")],
            transport=httpx2.MockTransport(extra_search_response),
        )
    assert str(ieee_error.value) == "IEEE Xplore requires QUIREBASE_IEEE_API_KEY"


def test_extra_search_fallback_identifiers_without_doi():
    def fallback_response(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.adsabs.harvard.edu":
            return httpx2.Response(
                200,
                json={
                    "response": {
                        "numFound": 1,
                        "docs": [
                            {
                                "bibcode": "2025ApJ...123..456A",
                                "title": ["NASA No-DOI result"],
                                "author": ["Astro Author"],
                                "pub": "ApJ",
                                "pubdate": "2025-01-01",
                            }
                        ],
                    }
                },
            )
        if request.url.host == "ieeexploreapi.ieee.org":
            return httpx2.Response(
                200,
                json={
                    "total_records": 1,
                    "articles": [
                        {
                            "title": "IEEE No-DOI result",
                            "article_number": "9876543",
                            "publication_title": "IEEE Journal",
                            "publication_year": 2025,
                            "authors": {"authors": [{"full_name": "Ieee Author"}]},
                        }
                    ],
                },
            )
        raise NotImplementedError(str(request.url))

    nasa_page = search_metadata(
        "nasa",
        [SearchClause("title", "and", "machine learning")],
        settings=SimpleNamespace(nasa_ads_token="ads-token"),
        transport=httpx2.MockTransport(fallback_response),
    )
    assert nasa_page.results[0].identifier == Identifier("bibcode", "2025ApJ...123..456A")

    ieee_page = search_metadata(
        "ieee",
        [SearchClause("title", "and", "machine learning")],
        settings=SimpleNamespace(ieee_api_key="ieee-key"),
        transport=httpx2.MockTransport(fallback_response),
    )
    assert ieee_page.results[0].identifier == Identifier("article_number", "9876543")
