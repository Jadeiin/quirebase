from types import SimpleNamespace

import httpx2
import pytest
from inquiro import (
    CandidateNotFound,
    CandidateRecord,
    Identifier,
    ProviderUnavailable,
)
from inquiro_provider_helpers import provider_runtime


def lookup_metadata(value, provider="auto", settings=None, transport=None):
    assert transport is not None
    with provider_runtime(settings=settings, transport=transport) as runtime:
        record = runtime.lookup(value, provider=provider)
    return record.identifier, record


def parse_identifier(value, provider="auto"):
    settings = SimpleNamespace(nasa_ads_token="ads-token", ieee_api_key="ieee-key")
    identifier, _record = lookup_metadata(
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
        return httpx2.Response(
            200,
            json={
                "result": {
                    "42": {
                        "title": "PubMed Example",
                        "authors": [{"name": "Doe J"}],
                        "fulljournalname": "Medical Journal",
                        "pubdate": "2024",
                        "articleids": [{"idtype": "doi", "value": "10.2/pubmed"}],
                    }
                }
            },
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
        ("1234567", "article_number", Identifier("article_number", "1234567")),
    ],
)
def test_identifier_detection(value, provider, expected):
    assert parse_identifier(value, provider) == expected


def test_auto_detection_does_not_match_bibcode():
    with pytest.raises(ValueError, match="not a recognized DOI"):
        parse_identifier("2025ApJ...123..456A", "auto")


def test_identifier_input_cannot_be_used_as_an_arbitrary_url():
    with pytest.raises(ValueError):
        parse_identifier("https://127.0.0.1/admin", "auto")


def test_pmc_does_not_offer_metadata_lookup():
    with pytest.raises(ValueError, match="unknown identifier provider: pmc"):
        lookup_metadata("PMC123", "pmc", transport=httpx2.MockTransport(response))


@pytest.mark.parametrize(
    ("value", "provider", "message"),
    [
        ("2025ApJ...123..456A", "bibcode", "NASA ADS requires INQUIRO_NASA_ADS_TOKEN"),
        ("1234567", "article_number", "IEEE Xplore requires INQUIRO_IEEE_API_KEY"),
    ],
)
def test_credentialed_lookup_errors_remain_provider_specific(value, provider, message):
    with pytest.raises(ProviderUnavailable) as error:
        lookup_metadata(value, provider, transport=httpx2.MockTransport(response))
    assert str(error.value) == message


@pytest.mark.parametrize(
    ("value", "provider"),
    [
        ("invalid", "bibcode"),
        ('" OR 1=1', "bibcode"),
        ("not-a-bibcode", "bibcode"),
        ("invalid-number", "article_number"),
    ],
)
def test_explicit_provider_rejects_malformed_identifiers(value, provider):
    with pytest.raises(ValueError, match=f"identifier is not a valid {provider}"):
        parse_identifier(value, provider)


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
        ("1234567", "article_number", "IEEE Example"),
    ],
)
def test_provider_adapters_map_records(value, provider, title):
    parsed, record = lookup_metadata(
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


def test_crossref_lookup_preserves_rich_candidate_metadata():
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

    _identifier, record = lookup_metadata(
        "10.1234/rich",
        "doi",
        transport=httpx2.MockTransport(rich_crossref_response),
    )

    assert record.keywords == "Machine Learning; Research methods"
    assert record.affiliation == "Example University; Research Lab"
    assert record.urls is not None
    assert record.urls.splitlines() == [
        "https://doi.org/10.1234/rich",
        "https://api.crossref.org/works/10.1234/rich",
        "https://example.org/article",
        "https://example.org/article.pdf",
        "https://example.org/supplement",
    ]


def test_metadata_response_size_is_limited():
    transport = httpx2.MockTransport(lambda _request: httpx2.Response(200, content=b"x" * 2048))
    with pytest.raises(ProviderUnavailable, match="size limit"):
        lookup_metadata(
            "10.1234/sample",
            "doi",
            settings=SimpleNamespace(metadata_max_response_bytes=1024),
            transport=transport,
        )


def test_lookup_404_is_a_typed_candidate_failure():
    transport = httpx2.MockTransport(lambda _request: httpx2.Response(404))
    with pytest.raises(CandidateNotFound, match="not found"):
        lookup_metadata("10.9999/missing", "doi", transport=transport)


@pytest.mark.parametrize("status_code", [301, 429, 503])
def test_lookup_transport_failures_share_one_error_contract(status_code):
    transport = httpx2.MockTransport(lambda _request: httpx2.Response(status_code))
    with pytest.raises(ProviderUnavailable):
        lookup_metadata("10.9999/failure", "doi", transport=transport)


def test_pubmed_lookup_passes_configured_identity_and_api_key():
    captured: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.update(request.url.params)
        return httpx2.Response(
            200,
            json={"result": {"42": {"title": "Configured PubMed", "authors": []}}},
        )

    _, record = lookup_metadata(
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
        identifier=Identifier("arxiv", "1706.03762"),
        title="Attention Is All You Need",
        abstract="The dominant sequence transduction models...",
        authors="Vaswani, Ashish; Shazeer, Noam",
        keywords="Machine Learning; Transformer",
        publication_date="2017-06-12",
        publication_title="NeurIPS 2017",
        volume="30",
        pages="5998-6008",
        doi="10.48550/arXiv.1706.03762",
        urls="https://arxiv.org/abs/1706.03762\nhttps://arxiv.org/pdf/1706.03762.pdf",
    )

    assert record.title == "Attention Is All You Need"
    assert record.volume == "30"

    with pytest.raises(AttributeError):
        record.title = "changed"


def test_openalex_abstract_inverted_index_and_html_cleaning():
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

    _ident, record = lookup_metadata(
        "W4391019623",
        "openalex",
        transport=httpx2.MockTransport(handler),
    )

    assert record.title == "OmniDrones: An Efficient Platform"
    assert record.abstract == "In this work, we introduce OmniDrones."
    assert record.authors == "Guanqi He; Jordan Key"
    assert record.keywords == "Robotics"
    assert "https://arxiv.org/abs/2309.12825" in str(record.urls)
