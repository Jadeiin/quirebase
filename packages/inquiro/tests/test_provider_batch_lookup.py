from __future__ import annotations

import asyncio
import json
from itertools import product
from urllib.parse import unquote

import pytest
from inquiro import (
    CandidateRecord,
    InvalidProviderRequest,
    LookupFailure,
    ProviderConfig,
    ProviderRuntime,
)
from inquiro.transport import MockExchange, TransportResponse

pytestmark = pytest.mark.anyio


async def test_pubmed_batch_matches_articles_and_books_by_pmid_in_input_order():
    xml = b"""<PubmedArticleSet>
      <PubmedBookArticle><BookDocument><PMID>43</PMID>
        <ArticleTitle>Book chapter</ArticleTitle><Book><BookTitle>Book</BookTitle></Book>
      </BookDocument></PubmedBookArticle>
      <PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
        <ArticleTitle>Journal article</ArticleTitle>
        <AuthorList><Author><LastName>Smith</LastName><ForeName>Jane</ForeName></Author></AuthorList>
      </Article></MedlineCitation></PubmedArticle>
    </PubmedArticleSet>"""
    exchange = MockExchange(lambda _: TransportResponse(200, xml))
    async with ProviderRuntime.with_exchange(ProviderConfig(), exchange) as runtime:
        outcomes = await runtime.lookup_many([
            "42",
            "43",
            "44",
            "https://pubmed.ncbi.nlm.nih.gov/42/",
        ])

    assert len(exchange.requests) == 1
    assert exchange.requests[0].url.endswith("/efetch.fcgi")
    assert exchange.requests[0].params["id"] == "42,43,44"
    assert [outcome.value for outcome in outcomes] == [
        "42",
        "43",
        "44",
        "https://pubmed.ncbi.nlm.nih.gov/42/",
    ]
    assert outcomes[0].result.work["title"] == "Journal article"
    assert outcomes[1].result.work["title"] == "Book chapter"
    assert outcomes[1].result.work["type"] == "BookChapter"
    assert outcomes[2].result.code == "not_found"
    assert outcomes[3].result.lookup_identifier.value == "42"
    outcomes[0].result.work["contributors"][0]["person"]["name"] = "Changed"
    assert outcomes[3].result.work["contributors"][0]["person"]["name"] == "Jane Smith"


async def test_arxiv_batch_keeps_requested_versions_and_resolves_latest_independently():
    xml = b"""<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>http://arxiv.org/abs/2304.08030v2</id><title>Second version</title></entry>
      <entry><id>http://arxiv.org/abs/2304.08030v3</id><title>Latest version</title></entry>
      <entry><id>http://arxiv.org/abs/2304.08030v1</id><title>First version</title></entry>
    </feed>"""
    exchange = MockExchange(lambda _: TransportResponse(200, xml))
    async with ProviderRuntime.with_exchange(ProviderConfig(), exchange) as runtime:
        outcomes = await runtime.lookup_many([
            "2304.08030v1",
            "2304.08030v2",
            "2304.08030",
            "2304.08031",
            "2304.08030v1",
        ])

    assert len(exchange.requests) == 1
    assert exchange.requests[0].params == {
        "id_list": "2304.08030v1,2304.08030v2,2304.08030,2304.08031",
        "max_results": "4",
    }
    assert [outcomes[index].result.work["title"] for index in (0, 1, 2, 4)] == [
        "First version",
        "Second version",
        "Latest version",
        "First version",
    ]
    assert outcomes[2].result.lookup_identifier.value == "2304.08030"
    assert any(
        identifier["identifier"] == "2304.08030v3"
        for identifier in outcomes[2].result.work["identifiers"]
    )
    assert outcomes[3].result.code == "not_found"


@pytest.mark.parametrize(
    "provider,values",
    [
        ("crossref", ["10.1234/one", "10.1234/two"]),
        ("openalex", ["W123", "10.1234/two"]),
    ],
)
async def test_batch_keeps_crossref_and_openalex_on_singleton_endpoints(provider, values):
    def response(request):
        assert not request.params or "filter" not in request.params
        assert request.url.rsplit("/", 1)[-1] != "works"
        if provider == "crossref":
            doi = unquote(request.url.rsplit("/", 1)[-1])
            payload = {"message": {"DOI": doi, "title": [doi], "type": "journal-article"}}
        else:
            payload = {
                "id": "https://openalex.org/W123",
                "display_name": "OpenAlex Work",
                "type": "article",
            }
        return TransportResponse(200, json.dumps(payload).encode())

    exchange = MockExchange(response)
    async with ProviderRuntime.with_exchange(ProviderConfig(), exchange) as runtime:
        outcomes = await runtime.lookup_many(values, provider=provider)

    assert len(exchange.requests) == 2
    assert all(isinstance(outcome.result, CandidateRecord) for outcome in outcomes)
    assert [outcome.result.lookup_identifier.value for outcome in outcomes] == values


async def test_singleton_requests_are_bounded_and_return_in_input_order():
    active = peak = 0
    completed = []
    release_first = asyncio.Event()

    async def response(request):
        nonlocal active, peak
        doi = unquote(request.url.rsplit("/", 1)[-1])
        active += 1
        peak = max(peak, active)
        try:
            if doi.endswith("/0"):
                await release_first.wait()
            else:
                await asyncio.sleep(0)
                release_first.set()
            return TransportResponse(
                200,
                json.dumps({
                    "message": {"DOI": doi, "title": [doi], "type": "journal-article"},
                }).encode(),
            )
        finally:
            active -= 1
            completed.append(doi)

    values = [f"10.1234/{index}" for index in range(8)]
    async with ProviderRuntime.with_exchange(ProviderConfig(), MockExchange(response)) as runtime:
        outcomes = await runtime.lookup_many(values)
    assert active == 0 and peak == 3
    assert completed[0] != values[0]
    assert [outcome.result.work["title"] for outcome in outcomes] == values


@pytest.mark.parametrize("status", [429, 503])
async def test_failed_native_request_retains_successful_siblings_without_fanning_out(status):
    def response(request):
        if "ncbi" in request.url:
            return TransportResponse(status)
        return TransportResponse(
            200, b'{"message":{"DOI":"10.1234/ok","title":["Good"],"type":"journal-article"}}'
        )

    exchange = MockExchange(response)
    async with ProviderRuntime.with_exchange(ProviderConfig(), exchange) as runtime:
        outcomes = await runtime.lookup_many(["42", "invalid", "43", "10.1234/ok"])
    assert len(exchange.requests) == 2
    assert [outcome.result.code for outcome in outcomes[:3]] == [
        "unavailable",
        "invalid_request",
        "unavailable",
    ]
    assert outcomes[3].result.work["title"] == "Good"


@pytest.mark.parametrize("repetitions", [1, 16])
async def test_oversized_native_response_is_split_without_relaxing_the_byte_limit(repetitions):
    def body(values):
        return (
            "<PubmedArticleSet>"
            + "".join(
                f"<PubmedArticle><MedlineCitation><PMID>{value}</PMID><Article>"
                f"<ArticleTitle>{'X' * (1000 if value == '43' else 20)}</ArticleTitle>"
                "</Article></MedlineCitation></PubmedArticle>"
                for value in values
            )
            + "</PubmedArticleSet>"
        ).encode()

    limit = len(body(["42"])) + 1
    exchange = MockExchange(
        lambda request: TransportResponse(200, body(request.params["id"].split(",")))
    )
    async with ProviderRuntime.with_exchange(
        ProviderConfig(max_response_bytes=limit), exchange
    ) as runtime:
        outcomes = await runtime.lookup_many(["42", "43", "44"] * repetitions)
    assert len(exchange.requests) == 5
    assert [outcome.value for outcome in outcomes] == ["42", "43", "44"] * repetitions
    assert all(isinstance(outcome.result, CandidateRecord) for outcome in outcomes[::3])
    assert all(isinstance(outcome.result, CandidateRecord) for outcome in outcomes[2::3])
    assert [outcome.result for outcome in outcomes[1::3]] == [
        LookupFailure("unavailable", "metadata response exceeded the size limit")
    ] * repetitions


@pytest.mark.parametrize(
    "provider,keys,aliases,parameter",
    [
        ("pubmed", ["42", "43"], ["https://pubmed.ncbi.nlm.nih.gov/42/", "PMID:43"], "id"),
        (
            "arxiv",
            ["2304.08030v1", "2304.08030v2"],
            ["https://arxiv.org/abs/2304.08030v1", "arxiv:2304.08030v2"],
            "id_list",
        ),
    ],
)
async def test_oversized_native_batches_split_distinct_keys_and_preserve_duplicate_inputs(
    provider, keys, aliases, parameter
):
    def body(values):
        if provider == "pubmed":
            return (
                "<PubmedArticleSet>"
                + "".join(
                    f"<PubmedArticle><MedlineCitation><PMID>{value}</PMID><Article>"
                    f"<ArticleTitle>Record {value}</ArticleTitle>"
                    "</Article></MedlineCitation></PubmedArticle>"
                    for value in reversed(values)
                )
                + "</PubmedArticleSet>"
            ).encode()
        return (
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            + "".join(
                f"<entry><id>https://arxiv.org/abs/{value}</id>"
                f"<title>Record {value}</title></entry>"
                for value in reversed(values)
            )
            + "</feed>"
        ).encode()

    values = ((keys + aliases) * 13)[:50]
    exchange = MockExchange(
        lambda request: TransportResponse(200, body(request.params[parameter].split(",")))
    )
    limit = max(len(body([key])) for key in keys)
    async with ProviderRuntime.with_exchange(
        ProviderConfig(max_response_bytes=limit), exchange
    ) as runtime:
        outcomes = await runtime.lookup_many(values, provider=provider)

    assert [request.params[parameter] for request in exchange.requests] == [",".join(keys), *keys]
    assert [outcome.value for outcome in outcomes] == values
    assert [outcome.result.lookup_identifier.value for outcome in outcomes] == keys * 25
    assert [outcome.result.work["title"] for outcome in outcomes] == [
        f"Record {keys[0]}",
        f"Record {keys[1]}",
    ] * 25
    outcomes[0].result.work["title"] = "Changed"
    assert outcomes[2].result.work["title"] == f"Record {keys[0]}"


@pytest.mark.parametrize("provider", ["pubmed", "arxiv"])
async def test_native_overflow_splits_equivalent_identifier_spellings_together(provider):
    if provider == "pubmed":
        keys = ["42", "43"]
        values = [key.zfill(width) for width in range(2, 11) for key in keys]
        values += ["\uff14\uff12", "٤٣", "٠٤٢", "\uff10\uff10\uff14\uff13"]
        parameter = "id"
    else:
        keys = ["hep-th/9901001v1", "hep-th/9901002v2"]
        prefixes = dict.fromkeys(
            "".join(chars) for chars in product(*[(c, c.upper()) for c in "hep-th"])
        )
        values = [prefix + key[6:] for prefix in list(prefixes)[:25] for key in keys]
        parameter = "id_list"

    def body(requested):
        canonical = dict.fromkeys(
            str(int(value)) if provider == "pubmed" else value.casefold() for value in requested
        )
        if provider == "pubmed":
            records = "".join(
                f"<PubmedArticle><MedlineCitation><PMID>{key}</PMID><Article>"
                f"<ArticleTitle>Record {key}</ArticleTitle></Article></MedlineCitation>"
                "</PubmedArticle>"
                for key in canonical
            )
            return f"<PubmedArticleSet>{records}</PubmedArticleSet>".encode()
        records = "".join(
            f"<entry><id>https://arxiv.org/abs/{key}</id><title>Record {key}</title></entry>"
            for key in canonical
        )
        return f'<feed xmlns="http://www.w3.org/2005/Atom">{records}</feed>'.encode()

    exchange = MockExchange(
        lambda request: TransportResponse(200, body(request.params[parameter].split(",")))
    )
    limit = max(len(body([key])) for key in keys)
    async with ProviderRuntime.with_exchange(
        ProviderConfig(max_response_bytes=limit), exchange
    ) as runtime:
        outcomes = await runtime.lookup_many(values, provider=provider)

    assert [request.params[parameter] for request in exchange.requests] == [",".join(keys), *keys]
    assert [outcome.value for outcome in outcomes] == values
    assert [outcome.result.lookup_identifier.value for outcome in outcomes] == keys * (
        len(values) // 2
    )


@pytest.mark.parametrize("values", [[], ["42"] * 51, "42", [42]])
async def test_batch_shape_errors_do_not_start_provider_requests(values):
    exchange = MockExchange(lambda _: pytest.fail("invalid batch made a request"))
    async with ProviderRuntime.with_exchange(ProviderConfig(), exchange) as runtime:
        with pytest.raises(InvalidProviderRequest):
            await runtime.lookup_many(values)


@pytest.mark.parametrize(
    "provider,values,body",
    [
        ("pubmed", ["42", "43"], b"<not-an-article-set/>"),
        (
            "pubmed",
            ["42", "43"],
            b"<PubmedArticleSet><ERROR>Unavailable</ERROR></PubmedArticleSet>",
        ),
        ("arxiv", ["2304.08030", "2304.08031"], b"<not-a-feed/>"),
        (
            "arxiv",
            ["2304.08030", "2304.08031"],
            b'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/"><o:totalResults>2</o:totalResults></feed>',
        ),
    ],
)
@pytest.mark.parametrize("input_count", [1, 2])
async def test_invalid_or_truncated_native_payload_is_not_reported_as_missing(
    provider, values, body, input_count
):
    exchange = MockExchange(lambda _: TransportResponse(200, body))
    async with ProviderRuntime.with_exchange(ProviderConfig(), exchange) as runtime:
        outcomes = await runtime.lookup_many(values[:input_count], provider=provider)
    assert all(outcome.result.code == "unavailable" for outcome in outcomes)
    assert len(exchange.requests) == 1


async def test_unusable_native_record_does_not_remove_valid_siblings():
    xml = b"""<PubmedArticleSet>
      <PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
        <ArticleTitle>Valid record</ArticleTitle>
      </Article></MedlineCitation></PubmedArticle>
      <PubmedArticle><MedlineCitation><PMID>43</PMID></MedlineCitation></PubmedArticle>
    </PubmedArticleSet>"""
    async with ProviderRuntime.with_exchange(
        ProviderConfig(), MockExchange(lambda _: TransportResponse(200, xml))
    ) as runtime:
        outcomes = await runtime.lookup_many(["42", "43"])
    assert outcomes[0].result.work["title"] == "Valid record"
    assert outcomes[1].result.code == "not_found"


async def test_unexpected_failure_cancels_and_joins_sibling_requests():
    started = asyncio.Event()
    stopped = asyncio.Event()
    closed = asyncio.Event()

    async def response(request):
        if "slow" in request.url:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        await started.wait()
        raise RuntimeError("unexpected adapter bug")

    class CheckedExchange(MockExchange):
        async def aclose(self):
            assert stopped.is_set()
            closed.set()

    with pytest.raises(ExceptionGroup) as raised:
        async with ProviderRuntime.with_exchange(
            ProviderConfig(), CheckedExchange(response)
        ) as runtime:
            await runtime.lookup_many(["10.1234/slow", "10.1234/broken"])
    assert str(raised.value.exceptions[0]) == "unexpected adapter bug"
    assert closed.is_set()


async def test_closed_runtime_rejects_batch_lookup_without_io():
    exchange = MockExchange(lambda _: pytest.fail("closed runtime made a request"))
    async with ProviderRuntime.with_exchange(ProviderConfig(), exchange) as runtime:
        pass
    with pytest.raises(RuntimeError, match="closed"):
        await runtime.lookup_many(["42"])


async def test_batch_snapshots_inputs_before_waiting_on_provider_io():
    values = ["10.1234/one", "10.1234/two"]

    async def response(request):
        values.clear()
        await asyncio.sleep(0)
        doi = unquote(request.url.rsplit("/", 1)[-1])
        return TransportResponse(
            200,
            json.dumps({
                "message": {"DOI": doi, "title": [doi], "type": "journal-article"},
            }).encode(),
        )

    async with ProviderRuntime.with_exchange(ProviderConfig(), MockExchange(response)) as runtime:
        outcomes = await runtime.lookup_many(values)
    assert [outcome.value for outcome in outcomes] == ["10.1234/one", "10.1234/two"]
