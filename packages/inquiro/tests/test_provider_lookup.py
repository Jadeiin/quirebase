import asyncio
import json
from types import SimpleNamespace

import httpx2
import pytest
from inquiro import (
    CandidateNotFound,
    CandidateRecord,
    Contributor,
    Identifier,
    ProviderConfig,
    ProviderRuntime,
    ProviderUnavailable,
    ResourceLink,
)
from inquiro.transport import MockExchange, TransportRequest, TransportResponse
from inquiro_provider_helpers import provider_runtime

pytestmark = pytest.mark.anyio


async def lookup_metadata(value, provider="auto", settings=None, transport=None):
    assert transport is not None
    async with provider_runtime(settings=settings, transport=transport) as runtime:
        record = await runtime.lookup(value, provider=provider)
    return record.lookup_identifier, record


async def parse_identifier(value, provider="auto"):
    settings = SimpleNamespace(nasa_ads_token="ads-token", ieee_api_key="ieee-key")
    identifier, _record = await lookup_metadata(
        value,
        provider,
        settings=settings,
        transport=httpx2.MockTransport(response),
    )
    return identifier


def response(request: httpx2.Request) -> httpx2.Response:
    if request.url.host == "api.crossref.org":
        if "10.9999" in str(request.url):
            return httpx2.Response(404)
        assert "/10.1234%2Fsample" in str(request.url)
        return httpx2.Response(
            200,
            json={
                "message": {
                    "title": ["DOI Example"],
                    "abstract": "<jats:p>An abstract</jats:p>",
                    "author": [{"family": "Doe", "given": "Jane"}],
                    "container-title": ["Journal"],
                    "published-online": {"date-parts": [[2025, 2, 3]]},
                    "DOI": "10.1234/sample",
                    "type": "journal-article",
                }
            },
        )
    if request.url.host == "eutils.ncbi.nlm.nih.gov":
        assert request.url.path.endswith("efetch.fcgi")
        return httpx2.Response(
            200,
            text="""<PubmedArticleSet><PubmedArticle>
        <MedlineCitation><PMID>42</PMID><Article><ArticleTitle>PubMed Example</ArticleTitle>
        <AuthorList><Author><LastName>Doe</LastName><ForeName>Jane</ForeName></Author></AuthorList>
        <Journal><Title>Medical Journal</Title><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal>
        </Article></MedlineCitation><PubmedData><ArticleIdList>
        <ArticleId IdType="doi">10.2/pubmed</ArticleId>
        </ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>""",
        )
    if request.url.host == "api.datacite.org":
        return httpx2.Response(
            200,
            json={
                "data": {
                    "attributes": {
                        "doi": "10.9999/dataset",
                        "titles": [{"title": "DataCite Example"}],
                        "creators": [{"name": "Example, Ada"}],
                        "publisher": "Repository",
                        "publicationYear": 2026,
                        "types": {"resourceTypeGeneral": "Dataset"},
                    }
                }
            },
        )
    if request.url.host == "api.openalex.org":
        assert request.url.path == "/works/W123"
        return httpx2.Response(
            200,
            json={
                "id": "https://openalex.org/W123",
                "display_name": "OpenAlex Example",
                "doi": "https://doi.org/10.4/openalex",
                "publication_date": "2026-01-01",
                "type": "article",
                "authorships": [{"author": {"display_name": "Alex Author"}}],
                "primary_location": {"source": {"display_name": "Open Journal"}},
                "topics": [{"display_name": "Open science"}],
            },
        )
    if request.url.host == "openlibrary.org":
        return httpx2.Response(
            200,
            json={
                "ISBN:9780131103627": {
                    "title": "The C Programming Language",
                    "authors": [{"name": "Brian Kernighan"}],
                    "publishers": [{"name": "Prentice Hall"}],
                    "publish_date": "1988",
                }
            },
        )
    if request.url.host == "api.adsabs.harvard.edu":
        assert "Bearer ads-token" in request.headers.get("Authorization", "")
        return httpx2.Response(
            200,
            json={
                "response": {
                    "docs": [
                        {
                            "bibcode": ["2025ApJ...123..456A"],
                            "title": ["NASA ADS Example"],
                            "author": ["Doe, Jane"],
                            "pub": ["ApJ"],
                            "pubdate": ["2025-01-01"],
                            "doi": ["10.1234/ads"],
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
                        "title": "IEEE Example",
                        "doi": "10.1234/ieee",
                        "article_number": "1234567",
                        "publication_title": "IEEE Trans",
                        "publication_year": "2025",
                        "authors": {"authors": [{"full_name": "Doe, Jane"}]},
                    }
                ]
            },
        )
    assert request.url.host == "export.arxiv.org"
    return httpx2.Response(
        200,
        text="""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry><title>arXiv Example</title><summary>Preprint abstract</summary>
          <published>2023-01-02T00:00:00Z</published><author><name>Ada Example</name></author>
          <category term="cs.CL"/><arxiv:doi>10.3/arxiv</arxiv:doi></entry>
        </feed>""",
    )


@pytest.mark.parametrize(
    ("value", "provider", "expected"),
    [
        ("https://doi.org/10.1234/sample", "auto", Identifier("doi", "10.1234/sample")),
        ("10.1234/sample", "doi", Identifier("doi", "10.1234/sample")),
        ("10.1234/sample", "crossref", Identifier("crossref", "10.1234/sample")),
        ("PMID: 42", "auto", Identifier("pmid", "42")),
        ("arXiv:1706.03762v7", "auto", Identifier("arxiv", "1706.03762v7")),
        ("ISBN 978-0-13-110362-7", "auto", Identifier("isbn", "9780131103627")),
        ("https://openalex.org/W123", "auto", Identifier("openalex", "W123")),
        ("2025ApJ...123..456A", "bibcode", Identifier("bibcode", "2025ApJ...123..456A")),
        ("bibcode: 2025ApJ...123..456A", "bibcode", Identifier("bibcode", "2025ApJ...123..456A")),
        ("1234567", "ieee", Identifier("ieee", "1234567")),
        ("ieee: 1234567", "ieee", Identifier("ieee", "1234567")),
        ("9780131103627", "openlibrary", Identifier("isbn", "9780131103627")),
        ("2025ApJ...123..456A", "nasa_ads", Identifier("bibcode", "2025ApJ...123..456A")),
    ],
)
async def test_identifier_detection(value, provider, expected):
    assert await parse_identifier(value, provider) == expected


async def test_auto_detection_does_not_match_bibcode():
    with pytest.raises(ValueError, match="not a recognized DOI"):
        await parse_identifier("2025ApJ...123..456A", "auto")


async def test_identifier_input_cannot_be_used_as_an_arbitrary_url():
    with pytest.raises(ValueError):
        await parse_identifier("https://127.0.0.1/admin", "auto")


async def test_pmc_does_not_offer_metadata_lookup():
    with pytest.raises(ValueError, match="unknown identifier provider: pmcid"):
        await lookup_metadata("PMC123", "pmc", transport=httpx2.MockTransport(response))


@pytest.mark.parametrize(
    ("value", "provider", "message"),
    [
        ("2025ApJ...123..456A", "bibcode", "NASA ADS requires INQUIRO_NASA_ADS_TOKEN"),
        ("1234567", "ieee", "IEEE Xplore requires INQUIRO_IEEE_API_KEY"),
    ],
)
async def test_credentialed_lookup_errors_remain_provider_specific(value, provider, message):
    with pytest.raises(ProviderUnavailable) as error:
        await lookup_metadata(value, provider, transport=httpx2.MockTransport(response))
    assert str(error.value) == message


@pytest.mark.parametrize(
    ("value", "provider"),
    [
        ("invalid", "bibcode"),
        ('" OR 1=1', "bibcode"),
        ("not-a-bibcode", "bibcode"),
        ("invalid-number", "ieee"),
    ],
)
async def test_explicit_provider_rejects_malformed_identifiers(value, provider):
    with pytest.raises(ValueError, match=f"identifier is not a valid {provider}"):
        await parse_identifier(value, provider)


@pytest.mark.parametrize(
    ("value", "provider", "title"),
    [
        ("10.1234/sample", "doi", "DOI Example"),
        ("42", "pmid", "PubMed Example"),
        ("1706.03762", "arxiv", "arXiv Example"),
        ("10.9999/dataset", "datacite", "DataCite Example"),
        ("9780131103627", "isbn", "The C Programming Language"),
        ("W123", "openalex", "OpenAlex Example"),
        ("2025ApJ...123..456A", "bibcode", "NASA ADS Example"),
        ("1234567", "ieee", "IEEE Example"),
    ],
)
async def test_provider_adapters_map_records(value, provider, title):
    parsed, record = await lookup_metadata(
        value,
        provider,
        settings=SimpleNamespace(
            metadata_contact_email="operator@example.org",
            nasa_ads_token="ads-token",
            ieee_api_key="ieee-key",
        ),
        transport=httpx2.MockTransport(response),
    )
    assert parsed.provider == provider
    assert record.title == title
    assert record.identifiers


@pytest.mark.parametrize(
    ("value", "provider", "source", "namespace"),
    [
        ("9780131103627", "openlibrary", "openlibrary", "isbn"),
        ("9780131103627", "isbn", "openlibrary", "isbn"),
        ("2025ApJ...123..456A", "nasa_ads", "nasa_ads", "bibcode"),
        ("2025ApJ...123..456A", "bibcode", "nasa_ads", "bibcode"),
        ("1234567", "ieee", "ieee", "ieee"),
        ("42", "pubmed", "pubmed", "pmid"),
        ("42", "pmid", "pubmed", "pmid"),
        ("10.9999/dataset", "datacite", "datacite", "doi"),
    ],
)
async def test_lookup_routes_source_names_and_namespaces_to_the_correct_adapter(
    value, provider, source, namespace
):
    _parsed, record = await lookup_metadata(
        value,
        provider,
        settings=SimpleNamespace(nasa_ads_token="ads-token", ieee_api_key="ieee-key"),
        transport=httpx2.MockTransport(response),
    )

    assert record.provider == source
    assert Identifier(namespace, value) in record.identifiers


@pytest.mark.parametrize(
    ("provider", "value", "source", "lookup_identifier", "identifiers"),
    [
        (
            "openalex",
            "10.1000/canonical",
            "openalex",
            Identifier("openalex", "10.1000/canonical"),
            (Identifier("openalex", "W123"), Identifier("doi", "10.1000/Canonical")),
        ),
        (
            "openalex",
            "W122",
            "openalex",
            Identifier("openalex", "W122"),
            (Identifier("openalex", "W123"), Identifier("doi", "10.1000/Canonical")),
        ),
        (
            "auto",
            "10.1000/canonical",
            "crossref",
            Identifier("doi", "10.1000/canonical"),
            (Identifier("doi", "10.1000/Canonical"),),
        ),
        (
            "crossref",
            "10.1000/canonical",
            "crossref",
            Identifier("crossref", "10.1000/canonical"),
            (Identifier("doi", "10.1000/Canonical"),),
        ),
        (
            "datacite",
            "10.1000/canonical",
            "datacite",
            Identifier("datacite", "10.1000/canonical"),
            (Identifier("doi", "10.1000/Canonical"),),
        ),
        (
            "bibcode",
            "2025ApJ...123..456A",
            "nasa_ads",
            Identifier("bibcode", "2025ApJ...123..456A"),
            (
                Identifier("bibcode", "2025ApJ...124..456A"),
                Identifier("doi", "10.1000/Canonical"),
            ),
        ),
        (
            "ieee",
            "1234566",
            "ieee",
            Identifier("ieee", "1234566"),
            (Identifier("ieee", "1234567"), Identifier("doi", "10.1000/Canonical")),
        ),
    ],
)
async def test_lookup_returns_record_identity_separately_from_request(
    provider, value, source, lookup_identifier, identifiers
):
    def handler(request):
        if request.url.host == "api.openalex.org":
            payload = {
                "id": "https://openalex.org/W123",
                "display_name": "Resolved Item",
                "doi": "https://doi.org/10.1000/Canonical",
            }
        elif request.url.host == "api.datacite.org":
            payload = {
                "data": {
                    "attributes": {
                        "doi": "10.1000/Canonical",
                        "titles": [{"title": "Resolved Item"}],
                    }
                }
            }
        elif request.url.host == "api.adsabs.harvard.edu":
            payload = {
                "response": {
                    "docs": [
                        {
                            "bibcode": "2025ApJ...124..456A",
                            "title": ["Resolved Item"],
                            "doi": ["10.1000/Canonical"],
                        }
                    ]
                }
            }
        elif request.url.host == "ieeexploreapi.ieee.org":
            payload = {
                "articles": [
                    {
                        "article_number": "1234567",
                        "title": "Resolved Item",
                        "doi": "10.1000/Canonical",
                    }
                ]
            }
        else:
            assert request.url.host == "api.crossref.org"
            payload = {"message": {"DOI": "10.1000/Canonical", "title": ["Resolved Item"]}}
        return httpx2.Response(200, json=payload)

    async with provider_runtime(
        settings=SimpleNamespace(nasa_ads_token="ads-token", ieee_api_key="ieee-key"),
        transport=httpx2.MockTransport(handler),
    ) as runtime:
        record = await runtime.lookup(value, provider=provider)

    assert record.provider == source
    assert record.lookup_identifier == lookup_identifier
    assert record.identifiers == identifiers


@pytest.mark.parametrize("work_id", [None, "https://openalex.org/invalid"])
async def test_openalex_lookup_requires_a_returned_work_identity(work_id):
    transport = httpx2.MockTransport(
        lambda request: httpx2.Response(
            200,
            json={"id": work_id, "display_name": "Unidentified Item", "doi": "10.1000/example"},
        )
    )
    with pytest.raises(ProviderUnavailable, match="Work ID"):
        await lookup_metadata("10.1000/example", "openalex", transport=transport)


async def test_crossref_lookup_preserves_rich_candidate_metadata():
    def rich_crossref_response(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "message": {
                    "title": ["Rich Crossref record"],
                    "DOI": "10.1234/rich",
                    "subject": ["Machine Learning", "<i>Research methods</i>"],
                    "author": [
                        {
                            "family": "Doe",
                            "given": "Jane",
                            "affiliation": [
                                {"name": "Example University"},
                                {"name": "Example University"},
                            ],
                        },
                        {"family": "Roe", "affiliation": [{"name": "Research Lab"}]},
                    ],
                    "URL": "https://api.crossref.org/works/10.1234/rich",
                    "resource": {"primary": {"URL": "https://example.org/article"}},
                    "link": [
                        {"URL": "https://example.org/article.pdf"},
                        {"URL": "https://example.org/supplement"},
                    ],
                }
            },
        )

    _identifier, record = await lookup_metadata(
        "10.1234/rich",
        "doi",
        transport=httpx2.MockTransport(rich_crossref_response),
    )

    assert record.keywords == ("Machine Learning", "Research methods")
    assert [
        affiliation.name for author in record.authors for affiliation in author.affiliations
    ] == ["Example University", "Research Lab"]
    assert record.urls is not None
    assert [link.url for link in record.urls] == [
        "https://doi.org/10.1234/rich",
        "https://api.crossref.org/works/10.1234/rich",
        "https://example.org/article",
        "https://example.org/article.pdf",
        "https://example.org/supplement",
    ]


async def test_metadata_response_size_is_limited():
    transport = httpx2.MockTransport(lambda _request: httpx2.Response(200, content=b"x" * 2048))
    with pytest.raises(ProviderUnavailable, match="size limit"):
        await lookup_metadata(
            "10.1234/sample",
            "doi",
            settings=SimpleNamespace(metadata_max_response_bytes=1024),
            transport=transport,
        )


async def test_lookup_404_is_a_typed_candidate_failure():
    transport = httpx2.MockTransport(lambda _request: httpx2.Response(404))
    with pytest.raises(CandidateNotFound, match="not found"):
        await lookup_metadata("10.9999/missing", "doi", transport=transport)


@pytest.mark.parametrize("status_code", [301, 429, 503])
async def test_lookup_transport_failures_share_one_error_contract(status_code):
    transport = httpx2.MockTransport(lambda _request: httpx2.Response(status_code))
    with pytest.raises(ProviderUnavailable):
        await lookup_metadata("10.9999/failure", "doi", transport=transport)


async def test_pubmed_lookup_passes_configured_identity_and_api_key():
    captured: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.update(request.url.params)
        return httpx2.Response(
            200,
            text="<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article><ArticleTitle>Configured PubMed</ArticleTitle><AuthorList /></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>",
        )

    _, record = await lookup_metadata(
        "42",
        "pmid",
        settings=SimpleNamespace(
            metadata_contact_email="operator@example.org",
            ncbi_api_key="secret-key",
        ),
        transport=httpx2.MockTransport(handler),
    )

    assert record.title == "Configured PubMed"
    assert captured["tool"] == "inquiro"
    assert captured["email"] == "operator@example.org"
    assert captured["api_key"] == "secret-key"


def test_candidate_record_is_an_immutable_normalized_value():
    record = CandidateRecord(
        provider="arxiv",
        lookup_identifier=Identifier("arxiv", "1706.03762"),
        title="Attention Is All You Need",
        abstract="The dominant sequence transduction models...",
        authors=(
            Contributor("Vaswani, Ashish"),
            Contributor("Shazeer, Noam"),
        ),
        keywords=("Machine Learning", "Transformer"),
        publication_date="2017-06-12",
        publication_title="NeurIPS 2017",
        volume="30",
        pages="5998-6008",
        doi="10.48550/arXiv.1706.03762",
        urls=(
            ResourceLink("https://arxiv.org/abs/1706.03762"),
            ResourceLink("https://arxiv.org/pdf/1706.03762.pdf"),
        ),
    )

    assert record.title == "Attention Is All You Need"
    assert record.volume == "30"

    with pytest.raises(AttributeError):
        record.title = "changed"


async def test_openalex_abstract_inverted_index_and_html_cleaning():
    mock_payload = {
        "id": "https://openalex.org/W4391019623",
        "doi": "https://doi.org/10.48550/arxiv.2309.12825",
        "title": "<i>OmniDrones:</i> An Efficient Platform",
        "display_name": "<i>OmniDrones:</i> An Efficient Platform",
        "publication_date": "2023-09-21",
        "abstract_inverted_index": {
            "In": [0],
            "this": [1],
            "work,": [2],
            "we": [3],
            "introduce": [4],
            "OmniDrones.": [5],
        },
        "authorships": [
            {"author": {"display_name": "Guanqi He"}},
            {"author": {"display_name": "Jordan Key"}},
        ],
        "topics": [{"display_name": "Robotics"}],
        "primary_location": {
            "source": {"display_name": "arXiv", "host_organization_name": "Cornell University"},
            "landing_page_url": "https://arxiv.org/abs/2309.12825",
        },
        "type": "preprint",
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=mock_payload)

    _ident, record = await lookup_metadata(
        "W4391019623",
        "openalex",
        transport=httpx2.MockTransport(handler),
    )

    assert record.title == "<i>OmniDrones:</i> An Efficient Platform"
    assert record.abstract == "In this work, we introduce OmniDrones."
    assert [author.display_name for author in record.authors] == ["Guanqi He", "Jordan Key"]
    assert record.keywords == ("Robotics",)
    assert "https://arxiv.org/abs/2309.12825" in str(record.urls)


async def test_slow_provider_lookup_does_not_block_an_independent_lookup():
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()

    async def send(request: TransportRequest) -> TransportResponse:
        title = "Fast result"
        if "slow" in request.url:
            slow_started.set()
            await release_slow.wait()
            title = "Slow result"
        return TransportResponse(
            200,
            json.dumps({"message": {"title": [title], "DOI": "10.1234/result"}}).encode(),
        )

    runtime = ProviderRuntime.with_exchange(ProviderConfig(), MockExchange(send))
    async with runtime:
        slow = asyncio.create_task(runtime.lookup("10.1234/slow", provider="doi"))
        await slow_started.wait()
        try:
            fast = await runtime.lookup("10.1234/fast", provider="doi")
            assert fast.title == "Fast result"
        finally:
            release_slow.set()
        assert (await slow).title == "Slow result"
