from __future__ import annotations

import json
from urllib.parse import quote

import pytest
from inquiro import (
    CandidateNotFound,
    Identifier,
    InvalidProviderRequest,
    ProviderConfig,
    ProviderRuntime,
    ProviderUnavailable,
    metadata_provider_choices,
)
from inquiro.transport import MockExchange, TransportResponse

pytestmark = pytest.mark.anyio


def work(doi="10.1000/example", **fields):
    return {
        "id": f"https://doi.org/{quote(doi, safe='/')}",
        "type": "Dataset",
        "title": "Example",
        **fields,
    }


@pytest.mark.parametrize("identifier", ["10.1000/example", "https://doi.org/10.1000/example"])
async def test_commonmeta_lookup_fetches_and_preserves_the_complete_work(identifier):
    snapshot = work(
        date_published="2026-01-02T12:34:56Z",
        identifiers=[
            {"identifier_type": "PMID", "identifier": "https://pubmed.ncbi.nlm.nih.gov/42"}
        ],
        license={"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
    )

    def source(request):
        assert request.url == "https://commonmeta.org/10.1000%2Fexample"
        assert request.params == {"format": "commonmeta"}
        assert request.headers["Accept"] == "application/vnd.commonmeta+json"
        return TransportResponse(200, json.dumps(snapshot).encode())

    async with ProviderRuntime.with_exchange(ProviderConfig(), MockExchange(source)) as runtime:
        record = await runtime.lookup(identifier, provider="commonmeta")
    assert record.provider == "commonmeta"
    assert record.lookup_identifier == Identifier("commonmeta", "10.1000/example")
    assert record.work == snapshot


def test_commonmeta_is_explicit_lookup_only_and_does_not_replace_default_doi_routing():
    choices = metadata_provider_choices()
    assert (
        next(choice for choice in choices.lookup if choice.id == "commonmeta").identifier_namespace
        == "doi"
    )
    assert "commonmeta" not in {choice.id for choice in choices.search}


@pytest.mark.parametrize("doi", ["10.1000/a?b", "10.1000/a#b", "10.1000/a%3c"])
async def test_commonmeta_rejects_remote_unsafe_doi_forms_before_network(doi):
    exchange = MockExchange(lambda request: pytest.fail("unsupported DOI must not be fetched"))
    async with ProviderRuntime.with_exchange(ProviderConfig(), exchange) as runtime:
        with pytest.raises(InvalidProviderRequest, match="Commonmeta"):
            await runtime.lookup(doi, provider="commonmeta")


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "https://orcid.org/0000-0002-1825-0097", "given_name": "Ada"},
        [work()],
        work("10.1000/wrong"),
        work(id="urn:uuid:00000000-0000-4000-8000-000000000001"),
    ],
)
async def test_commonmeta_rejects_invalid_or_unrelated_work_responses(payload):
    exchange = MockExchange(lambda request: TransportResponse(200, json.dumps(payload).encode()))
    async with ProviderRuntime.with_exchange(ProviderConfig(), exchange) as runtime:
        with pytest.raises(ProviderUnavailable):
            await runtime.lookup("10.1000/example", provider="commonmeta")


@pytest.mark.parametrize(
    "status,expected",
    [
        (404, CandidateNotFound),
        (502, ProviderUnavailable),
        (429, ProviderUnavailable),
        (308, ProviderUnavailable),
    ],
)
async def test_commonmeta_retains_transport_error_semantics(status, expected):
    exchange = MockExchange(lambda request: TransportResponse(status, b"upstream request failed"))
    async with ProviderRuntime.with_exchange(ProviderConfig(), exchange) as runtime:
        with pytest.raises(expected):
            await runtime.lookup("10.1000/example", provider="commonmeta")
