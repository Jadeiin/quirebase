from __future__ import annotations

import pytest
from inquiro import LookupFailure, ProviderConfig, ProviderRateLimited, ProviderRuntime
from inquiro.transport import MockExchange, TransportResponse

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"Retry-After": "7"}, 7.0),
        ({"rEtRy-AfTeR": "0"}, 0.0),
        (
            {
                "Date": "Wed, 21 Oct 2015 07:28:00 GMT",
                "Retry-After": "Wed, 21 Oct 2015 07:28:20 GMT",
            },
            20.0,
        ),
        (
            {
                "Date": "Wed, 21 Oct 2015 07:28:00 GMT",
                "Retry-After": "Wed, 21 Oct 2015 07:27:00 GMT",
            },
            0.0,
        ),
        ({"Retry-After": "-1"}, None),
        ({"Retry-After": "not-a-delay"}, None),
        ({}, None),
    ],
)
@pytest.mark.parametrize("provider", ["crossref", "openalex"])
async def test_rate_limit_preserves_retry_after_without_an_immediate_fallback(
    provider, headers, expected
):
    exchange = MockExchange(lambda _: TransportResponse(429, headers=headers))
    async with ProviderRuntime.with_exchange(ProviderConfig(), exchange) as runtime:
        with pytest.raises(ProviderRateLimited) as raised:
            await runtime.lookup("10.1234/example", provider=provider)
    assert raised.value.retry_after_seconds == expected
    assert len(exchange.requests) == 1


@pytest.mark.parametrize(
    "provider,values,requests",
    [
        ("arxiv", ["2304.08030v1", "2304.08031v1"], 1),
        ("pubmed", ["12345", "12346"], 1),
        ("crossref", ["10.1234/first", "10.1234/second"], 2),
        ("openalex", ["10.1234/first", "10.1234/second"], 2),
    ],
)
async def test_batch_outcomes_preserve_rate_limit_delay_without_retrying(
    provider, values, requests
):
    exchange = MockExchange(lambda _: TransportResponse(429, headers={"Retry-After": "17"}))
    async with ProviderRuntime.with_exchange(ProviderConfig(), exchange) as runtime:
        outcomes = await runtime.lookup_many(values, provider=provider)
    assert [outcome.value for outcome in outcomes] == values
    assert [outcome.result for outcome in outcomes] == [
        LookupFailure("unavailable", "metadata provider rate limit was reached", True, 17.0)
    ] * 2
    assert len(exchange.requests) == requests
