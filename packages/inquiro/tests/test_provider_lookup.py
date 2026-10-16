from types import SimpleNamespace

import httpx2
import pytest
from inquiro import (
    CandidateNotFound,
    Identifier,
    ProviderUnavailable,
    SearchClause,
    SearchQuery,
)
from inquiro_provider_helpers import provider_runtime

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "provider,identifier,source_doi",
    [
        ("pubmed", "42", "10.2/pubmed"),
        ("arxiv", "2401.00001", "10.3/arxiv"),
        ("ieee", "1234567", "10.1234/ieee"),
        ("nasa_ads", "2025ApJ...123..456A", "10.1234/ads"),
    ],
)
@pytest.mark.parametrize("doi", ["10.1234/Äbc", "10.1234/A%3c", "10.1234/X?#"])
async def test_provider_doi_uri_is_encoded_without_changing_raw_identifier(
    provider, identifier, source_doi, doi
):
    from urllib.parse import quote

    from inquiro.identifiers import canonical_doi
    from inquiro.work import work_identifiers

    def returned(request):
        original = response(request)
        return httpx2.Response(
            200, content=original.content.replace(source_doi.encode(), doi.encode())
        )

    _, record = await lookup_metadata(
        identifier,
        provider,
        settings=SimpleNamespace(nasa_ads_token="ads-token", ieee_api_key="ieee-key"),
        transport=httpx2.MockTransport(returned),
    )
    assert record.work["id"] == f"https://doi.org/{quote(canonical_doi(doi), safe='/')}"
    assert {"identifier_type": "DOI", "identifier": doi} in record.work["identifiers"]
    assert ("doi", canonical_doi(doi)) in work_identifiers(record.work)


@pytest.mark.parametrize(
    "provider,identifier,source_doi",
    [
        ("crossref", "10.1234/sample", "10.1234/sample"),
        ("datacite", "10.1234/sample", "10.9999/dataset"),
        ("openalex", "W1230000000", "https://doi.org/10.1234/openalex"),
    ],
)
@pytest.mark.parametrize("doi", ["10.1234/Über", "10.1234/über", "10.1234/A%3c", "10.123456/Über"])
async def test_native_provider_conversion_preserves_doi_identity(
    provider, identifier, source_doi, doi
):
    from urllib.parse import quote

    from inquiro.identifiers import canonical_doi
    from inquiro.work import work_identifiers

    def returned(request):
        original = response(request)
        value = f"https://doi.org/{quote(doi, safe='/')}" if provider == "openalex" else doi
        return httpx2.Response(
            200, content=original.content.replace(source_doi.encode(), value.encode())
        )

    _, record = await lookup_metadata(
        identifier, provider, transport=httpx2.MockTransport(returned)
    )
    assert ("doi", canonical_doi(doi)) in work_identifiers(record.work)
    assert record.work["id"].isascii()


@pytest.mark.parametrize("provider", ["auto", "pubmed", "pmid"])
@pytest.mark.parametrize(
    "identifier",
    [
        "https://pubmed.ncbi.nlm.nih.gov/42",
        "https://pubmed.ncbi.nlm.nih.gov/42/",
        "https://www.ncbi.nlm.nih.gov/pubmed/42/",
    ],
)
async def test_pubmed_resolver_urls_use_the_same_lookup_key_as_bare_ids(provider, identifier):
    key, _ = await lookup_metadata(identifier, provider, transport=httpx2.MockTransport(response))
    assert key == Identifier("pmid", "42")


async def lookup_metadata(value, provider="auto", settings=None, transport=None):
    assert transport is not None
    async with provider_runtime(settings=settings, transport=transport) as runtime:
        record = await runtime.lookup(value, provider=provider)
    return (record.lookup_identifier, record)


@pytest.mark.parametrize(
    "published,expected",
    [
        ("2024-06-00", "2024-06"),
        ("2024-00-00", "2024"),
        ("2024-02-30", "2024-02"),
        ("2024", "2024"),
        ("2024-06", "2024-06"),
        ("2024-02-29", "2024-02-29"),
        ("2024-06-15T12:34:56Z", "2024-06-15T12:34:56Z"),
        ("2024-06-15T12:34:56+08:00", "2024-06-15T12:34:56+08:00"),
    ],
)
async def test_provider_dates_retain_known_calendar_precision_in_lookup_and_search(
    published, expected
):
    def returned(request):
        return httpx2.Response(
            200,
            json={
                "response": {
                    "docs": [
                        {
                            "bibcode": "2025ApJ...123..456A",
                            "title": ["Provider date"],
                            "pubdate": published,
                        }
                    ],
                    "numFound": 1,
                }
            },
        )

    async with provider_runtime(
        settings=SimpleNamespace(nasa_ads_token="ads-token"),
        transport=httpx2.MockTransport(returned),
    ) as runtime:
        looked_up = await runtime.lookup("2025ApJ...123..456A", provider="nasa_ads")
        page = await runtime.search(
            SearchQuery("nasa_ads", (SearchClause("title", "and", "Provider date"),))
        )
    assert len(page.results) == 1
    assert looked_up.work["date_published"] == expected
    assert page.results[0].work["date_published"] == expected


async def parse_identifier(value, provider="auto"):
    settings = SimpleNamespace(nasa_ads_token="ads-token", ieee_api_key="ieee-key")
    identifier, _record = await lookup_metadata(
        value, provider, settings=settings, transport=httpx2.MockTransport(response)
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
            text='<PubmedArticleSet><PubmedArticle>\n        <MedlineCitation><PMID>42</PMID><Article><ArticleTitle>PubMed Example</ArticleTitle>\n        <AuthorList><Author><LastName>Doe</LastName><ForeName>Jane</ForeName></Author></AuthorList>\n        <Journal><Title>Medical Journal</Title><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal>\n        </Article></MedlineCitation><PubmedData><ArticleIdList>\n        <ArticleId IdType="doi">10.2/pubmed</ArticleId>\n        </ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>',
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
        assert request.url.path == "/works/W1230000000"
        return httpx2.Response(
            200,
            json={
                "id": "https://openalex.org/W1230000000",
                "display_name": "OpenAlex Example",
                "doi": "https://doi.org/10.1234/openalex",
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
        text='<?xml version="1.0"?>\n        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">\n          <entry><title>arXiv Example</title><summary>Preprint abstract</summary>\n          <published>2023-01-02T00:00:00Z</published><author><name>Ada Example</name></author>\n          <category term="cs.CL"/><arxiv:doi>10.3/arxiv</arxiv:doi></entry>\n        </feed>',
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
        ("https://openalex.org/W1230000000", "auto", Identifier("openalex", "W1230000000")),
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


@pytest.mark.parametrize("provider", ["auto", "pubmed", "pmid", "pmc", "pmcid"])
async def test_malformed_pubmed_url_is_a_provider_request_error(provider):
    from inquiro import InvalidProviderRequest

    with pytest.raises(InvalidProviderRequest):
        await parse_identifier("https://[bad", provider)


@pytest.mark.parametrize(
    "value, provider, title",
    [
        ("10.1234/sample", "crossref", "Crossref sample"),
        ("W1230000000", "openalex", "OpenAlex sample"),
        ("42", "pubmed", "PubMed sample"),
        ("2401.00001", "arxiv", "arXiv sample"),
        ("9780131103627", "openlibrary", "Open Library sample"),
        ("2025ApJ...123..456A", "nasa_ads", "NASA ADS sample"),
        ("1234567", "ieee", "IEEE sample"),
        ("10.1234/sample", "datacite", "DataCite sample"),
    ],
)
async def test_provider_outputs_valid_commonmeta(value, provider, title):
    from inquiro import Work

    settings = SimpleNamespace(nasa_ads_token="ads-token", ieee_api_key="ieee-key")
    async with provider_runtime(
        settings=settings, transport=httpx2.MockTransport(response)
    ) as runtime:
        candidate = await runtime.lookup(value, provider=provider)
    assert candidate.lookup_identifier.value == value
    assert candidate.work["title"]
    assert (
        Work.model_validate(candidate.work).model_dump(mode="json", exclude_none=True)
        == candidate.work
    )


async def test_lookup_preserves_query_context_without_claiming_it_as_identity():
    from inquiro.work import work_identifiers

    def returned(request):
        return httpx2.Response(
            200,
            json={
                "message": {
                    "DOI": "10.1234/confirmed",
                    "type": "journal-article",
                    "title": ["Confirmed"],
                }
            },
        )

    async with provider_runtime(transport=httpx2.MockTransport(returned)) as runtime:
        candidate = await runtime.lookup("10.1234/query", provider="crossref")
    assert candidate.lookup_identifier == Identifier("crossref", "10.1234/query")
    assert work_identifiers(candidate.work) == {("doi", "10.1234/confirmed")}


async def test_invalid_openalex_identity_is_not_confirmed():
    from inquiro.work import work_identifiers

    async with provider_runtime(
        transport=httpx2.MockTransport(
            lambda request: httpx2.Response(
                200, json={"id": "https://openalex.org/invalid", "title": "Invalid"}
            )
        )
    ) as runtime:
        result = await runtime.lookup("W1234567890", provider="openalex")
    assert work_identifiers(result.work) == set()
    assert result.lookup_identifier.value == "W1234567890"


async def test_lookup_404_is_a_typed_candidate_failure():
    async with provider_runtime(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(404))
    ) as runtime:
        with pytest.raises(CandidateNotFound):
            await runtime.lookup("10.1234/missing")


async def test_crossref_missing_optional_link_media_type_does_not_crash():
    def returned(request):
        return httpx2.Response(
            200,
            json={
                "message": {
                    "DOI": "10.1234/sample",
                    "type": "journal-article",
                    "title": ["Test"],
                    "link": [{"URL": "https://example.org/test.pdf"}],
                }
            },
        )

    async with provider_runtime(transport=httpx2.MockTransport(returned)) as runtime:
        result = await runtime.lookup("10.1234/sample")
    assert result.work["files"][0]["url"] == "https://example.org/test.pdf"


async def test_openalex_identifiers_use_urls_and_files_are_not_duplicated():
    from inquiro.work import work_identifiers

    payload = {
        "id": "https://openalex.org/W1230000000",
        "doi": "https://doi.org/10.1000/example",
        "ids": {
            "openalex": "https://openalex.org/W1230000000",
            "doi": "https://doi.org/10.1000/example",
        },
        "display_name": "Canonical OpenAlex identifiers",
        "primary_location": {"pdf_url": "https://example.test/paper.pdf"},
        "best_oa_location": {"pdf_url": "https://example.test/paper.pdf"},
    }
    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=payload))
    ) as runtime:
        record = await runtime.lookup("W1230000000", provider="openalex")
    assert record.work["files"] == [
        {"url": "https://example.test/paper.pdf", "mime_type": "application/pdf"}
    ]
    assert [row for row in record.work["identifiers"] if row["identifier_type"] == "OpenAlex"] == [
        {"identifier_type": "OpenAlex", "identifier": "https://openalex.org/W1230000000"}
    ]
    assert work_identifiers(record.work) == {
        ("openalex", "W1230000000"),
        ("doi", "10.1000/example"),
    }


async def test_crossref_empty_license_is_accepted_in_lookup():
    payload = {
        "DOI": "10.1234/sample",
        "type": "journal-article",
        "title": ["No license"],
        "license": [],
    }
    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={"message": payload}))
    ) as runtime:
        record = await runtime.lookup("10.1234/sample", provider="crossref")
    assert record.work["title"] == "No license"
    assert "license" not in record.work


@pytest.mark.parametrize(
    "provider,value",
    [
        ("arxiv", "2401.00001"),
        ("pubmed", "42"),
        ("openlibrary", "9780131103627"),
        ("ieee", "1234567"),
        ("nasa_ads", "2025ApJ...123..456A"),
    ],
)
@pytest.mark.parametrize("nameless", [False, True])
async def test_authorless_lookup_records_omit_contributors(provider, value, nameless):
    def returned(request):
        if provider == "arxiv":
            author = "<author><name> </name></author>" if nameless else ""
            return httpx2.Response(
                200,
                text=f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Authorless</title>{author}</entry></feed>',
            )
        if provider == "pubmed":
            author = "<Author><LastName> </LastName></Author>" if nameless else ""
            return httpx2.Response(
                200,
                text=f"<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article><ArticleTitle>Authorless</ArticleTitle><AuthorList>{author}</AuthorList></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>",
            )
        authors = [{"name": " "}] if nameless else []
        if provider == "openlibrary":
            payload = {f"ISBN:{value}": {"title": "Authorless", "authors": authors}}
        elif provider == "ieee":
            payload = {
                "articles": [
                    {
                        "title": "Authorless",
                        "article_number": value,
                        "authors": {"authors": [{"full_name": " "}] if nameless else []},
                    }
                ]
            }
        else:
            payload = {
                "response": {
                    "docs": [
                        {
                            "title": ["Authorless"],
                            "bibcode": value,
                            "author": [" "] if nameless else [],
                            "aff": [" "] if nameless else [],
                        }
                    ]
                }
            }
        return httpx2.Response(200, json=payload)

    async with provider_runtime(
        settings=SimpleNamespace(nasa_ads_token="ads-token", ieee_api_key="ieee-key"),
        transport=httpx2.MockTransport(returned),
    ) as runtime:
        record = await runtime.lookup(value, provider=provider)
    assert record.work["title"] == "Authorless"
    assert "contributors" not in record.work
