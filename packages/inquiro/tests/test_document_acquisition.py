from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import httpx2
import pytest
from inquiro import (
    DocumentRequest,
    InvalidPdfResponse,
    PdfAccessDenied,
    PdfNotAvailable,
    ProviderConfig,
    ProviderRuntime,
    ProviderUnavailable,
)
from inquiro.transport import MockExchange, TransportRequest, TransportResponse
from inquiro_provider_helpers import provider_runtime

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
pytestmark = pytest.mark.anyio


async def test_direct_url_download_returns_a_managed_pdf() -> None:
    def response(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["Accept"] == "application/pdf"
        return httpx2.Response(200, content=PDF)

    async with provider_runtime(transport=httpx2.MockTransport(response)) as runtime:
        async with await runtime.acquire_document(
            DocumentRequest("https://papers.example.org/article.pdf")
        ) as document:
            stream = document.stream
            assert await asyncio.to_thread(stream.read) == PDF
            assert document.filename == "article.pdf"
            assert document.media_type == "application/pdf"
            assert document.size_bytes == len(PDF)
            assert document.sha256 == hashlib.sha256(PDF).hexdigest()
            assert document.provider is None
        assert stream.closed


async def test_direct_url_download_follows_pdf_redirects() -> None:
    def response(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "papers.example.org":
            return httpx2.Response(
                302,
                headers={"Location": "https://cdn.example.org/files/final.pdf"},
            )
        assert request.url == "https://cdn.example.org/files/final.pdf"
        return httpx2.Response(200, content=PDF)

    async with (
        provider_runtime(transport=httpx2.MockTransport(response)) as runtime,
        await runtime.acquire_document(
            DocumentRequest("https://papers.example.org/download")
        ) as document,
    ):
        assert document.filename == "final.pdf"


@pytest.mark.parametrize(
    "path",
    ("%2E%2E%2Fevil.pdf", "%2E%2E%5Cevil.pdf", "evil%00.pdf"),
)
async def test_direct_url_filename_cannot_restore_unsafe_encoded_characters(path: str) -> None:
    def response(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=PDF)

    async with (
        provider_runtime(transport=httpx2.MockTransport(response)) as runtime,
        await runtime.acquire_document(
            DocumentRequest(f"https://example.org/files/{path}")
        ) as document,
    ):
        assert document.filename == "evil.pdf"


@pytest.mark.parametrize(
    "source",
    ("arXiv:1706.03762v7", "https://arxiv.org/abs/1706.03762v7"),
)
async def test_arxiv_identifier_uses_the_native_pdf_adapter(source: str) -> None:
    def response(request: httpx2.Request) -> httpx2.Response:
        assert request.url == "https://arxiv.org/pdf/1706.03762v7.pdf"
        return httpx2.Response(200, content=PDF)

    async with (
        provider_runtime(transport=httpx2.MockTransport(response)) as runtime,
        await runtime.acquire_document(DocumentRequest(source)) as document,
    ):
        assert document.filename == "1706.03762v7.pdf"
        assert document.provider == "arxiv"


@pytest.mark.parametrize("source", ("W123", "https://openalex.org/W123"))
async def test_openalex_work_uses_the_content_endpoint(source: str) -> None:
    def response(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/works/W123.pdf"
        assert request.url.params["api_key"] == "openalex-key"
        return httpx2.Response(200, content=PDF)

    settings = SimpleNamespace(openalex_api_key="openalex-key")
    async with (
        provider_runtime(settings=settings, transport=httpx2.MockTransport(response)) as runtime,
        await runtime.acquire_document(DocumentRequest(source)) as document,
    ):
        assert document.filename == "W123.pdf"
        assert document.provider == "openalex"


async def test_openalex_doi_resolves_the_work_before_download() -> None:
    def response(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.openalex.org":
            assert request.url.path == "/works/doi:10.1234/example"
            return httpx2.Response(
                200,
                json={
                    "id": "https://openalex.org/W456",
                    "has_content": {"pdf": True},
                },
            )
        assert request.url.path == "/works/W456.pdf"
        return httpx2.Response(200, content=PDF)

    settings = SimpleNamespace(openalex_api_key="openalex-key")
    async with (
        provider_runtime(settings=settings, transport=httpx2.MockTransport(response)) as runtime,
        await runtime.acquire_document(
            DocumentRequest("10.1234/example", provider="openalex")
        ) as document,
    ):
        assert document.filename == "W456.pdf"


async def test_openalex_pdf_requires_its_content_credential() -> None:
    async with provider_runtime(transport=httpx2.MockTransport(lambda _request: None)) as runtime:
        with pytest.raises(ProviderUnavailable, match="INQUIRO_OPENALEX_API_KEY"):
            await runtime.acquire_document(DocumentRequest("W123", provider="openalex"))


@pytest.mark.parametrize("source", ("10.1234/example", "https://doi.org/10.1234/example"))
async def test_crossref_doi_downloads_the_declared_pdf_link(source: str) -> None:
    def response(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "api.crossref.org":
            return httpx2.Response(
                200,
                json={
                    "message": {
                        "link": [
                            {
                                "URL": "https://publisher.example.org/article/full-text",
                                "content-type": "application/pdf",
                            }
                        ]
                    }
                },
            )
        assert request.url == "https://publisher.example.org/article/full-text"
        return httpx2.Response(200, content=PDF)

    async with (
        provider_runtime(transport=httpx2.MockTransport(response)) as runtime,
        await runtime.acquire_document(DocumentRequest(source)) as document,
    ):
        assert document.provider == "crossref"
        assert await asyncio.to_thread(document.stream.read) == PDF


async def test_crossref_doi_without_a_pdf_link_is_not_available() -> None:
    def response(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"message": {"link": []}})

    async with provider_runtime(transport=httpx2.MockTransport(response)) as runtime:
        with pytest.raises(PdfNotAvailable, match="does not provide a PDF link"):
            await runtime.acquire_document(DocumentRequest("10.1234/example"))


async def test_pmc_uses_the_latest_aws_article_version() -> None:
    def response(request: httpx2.Request) -> httpx2.Response:
        if request.url.params.get("list-type") == "2":
            return httpx2.Response(
                200,
                text="""<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
                  <CommonPrefixes><Prefix>PMC123.1/</Prefix></CommonPrefixes>
                  <CommonPrefixes><Prefix>PMC123.2/</Prefix></CommonPrefixes>
                </ListBucketResult>""",
            )
        if request.url.path == "/metadata/PMC123.2.json":
            return httpx2.Response(
                200,
                json={
                    "pdf_url": ("s3://pmc-oa-opendata/PMC123.2/PMC123.2.pdf?md5=0123456789abcdef")
                },
            )
        assert request.url.path == "/PMC123.2/PMC123.2.pdf"
        assert not request.url.query
        return httpx2.Response(200, content=PDF)

    async with (
        provider_runtime(transport=httpx2.MockTransport(response)) as runtime,
        await runtime.acquire_document(DocumentRequest("PMC123")) as document,
    ):
        assert document.filename == "PMC123.2.pdf"
        assert document.provider == "pmc"


async def test_pmc_normalizes_malformed_article_metadata_shape() -> None:
    def response(request: httpx2.Request) -> httpx2.Response:
        if request.url.params.get("list-type") == "2":
            return httpx2.Response(
                200,
                text="""<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
                  <CommonPrefixes><Prefix>PMC123.1/</Prefix></CommonPrefixes>
                </ListBucketResult>""",
            )
        return httpx2.Response(200, json=[])

    async with provider_runtime(transport=httpx2.MockTransport(response)) as runtime:
        with pytest.raises(ProviderUnavailable, match="invalid article metadata"):
            await runtime.acquire_document(DocumentRequest("PMC123"))


async def test_ieee_downloads_documented_pdf_url_for_open_access_article() -> None:
    def response(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "ieeexploreapi.ieee.org":
            assert request.url.path == "/api/v1/search/articles"
            assert request.url.params["apikey"] == "ieee-key"
            return httpx2.Response(
                200,
                json={
                    "articles": [
                        {
                            "article_number": "1234567",
                            "accessType": "Open Access",
                            "pdf_url": "https://ieeexplore.ieee.org/document/1234567.pdf",
                        }
                    ]
                },
            )
        return httpx2.Response(200, content=PDF)

    settings = SimpleNamespace(ieee_api_key="ieee-key")
    async with (
        provider_runtime(settings=settings, transport=httpx2.MockTransport(response)) as runtime,
        await runtime.acquire_document(
            DocumentRequest("1234567", provider="article_number")
        ) as document,
    ):
        assert document.filename == "1234567.pdf"
        assert document.provider == "ieee"


async def test_ieee_locked_article_reports_access_denied_without_downloading() -> None:
    def response(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "articles": [
                    {
                        "article_number": "1234567",
                        "accessType": "Locked",
                        "pdf_url": "https://ieeexplore.ieee.org/locked.pdf",
                    }
                ]
            },
        )

    settings = SimpleNamespace(ieee_api_key="ieee-key")
    async with provider_runtime(
        settings=settings, transport=httpx2.MockTransport(response)
    ) as runtime:
        with pytest.raises(PdfAccessDenied, match="not openly accessible"):
            await runtime.acquire_document(DocumentRequest("1234567", provider="article_number"))


@pytest.mark.parametrize(
    ("document_request", "settings"),
    (
        (DocumentRequest("10.1234/example"), None),
        (
            DocumentRequest("10.1234/example", provider="openalex"),
            SimpleNamespace(openalex_api_key="openalex-key"),
        ),
        (
            DocumentRequest("1234567", provider="article_number"),
            SimpleNamespace(ieee_api_key="ieee-key"),
        ),
    ),
)
async def test_document_adapters_normalize_malformed_json_shapes(
    document_request: DocumentRequest,
    settings: SimpleNamespace | None,
) -> None:
    def response(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[])

    async with provider_runtime(
        settings=settings, transport=httpx2.MockTransport(response)
    ) as runtime:
        with pytest.raises(ProviderUnavailable, match="invalid document metadata"):
            await runtime.acquire_document(document_request)


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (404, PdfNotAvailable),
        (401, PdfAccessDenied),
        (403, PdfAccessDenied),
    ],
)
async def test_pdf_download_exposes_actionable_errors(
    status_code: int,
    error_type: type[Exception],
) -> None:
    def response(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status_code)

    async with provider_runtime(transport=httpx2.MockTransport(response)) as runtime:
        with pytest.raises(error_type):
            await runtime.acquire_document(DocumentRequest("https://example.org/paper.pdf"))


async def test_pdf_download_rejects_non_pdf_and_oversized_responses() -> None:
    responses = iter((b"<html>not a PDF</html>", PDF))

    def send(_request: TransportRequest) -> TransportResponse:
        return TransportResponse(200, next(responses))

    runtime = ProviderRuntime.with_exchange(
        ProviderConfig(max_document_bytes=len(PDF) - 1),
        MockExchange(send),
    )
    async with runtime:
        with pytest.raises(InvalidPdfResponse, match="non-PDF"):
            await runtime.acquire_document(DocumentRequest("https://example.org/not-pdf"))
        with pytest.raises(InvalidPdfResponse, match="size limit"):
            await runtime.acquire_document(DocumentRequest("https://example.org/large.pdf"))


async def test_metadata_requests_still_reject_redirects() -> None:
    def response(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302, headers={"Location": "https://example.org/metadata"})

    async with provider_runtime(transport=httpx2.MockTransport(response)) as runtime:
        with pytest.raises(ProviderUnavailable, match="unexpected redirect"):
            await runtime.lookup("10.1234/example")


async def test_pdf_download_accepts_case_insensitive_redirect_location() -> None:
    requests: list[str] = []

    def send(request: TransportRequest) -> TransportResponse:
        requests.append(request.url)
        if len(requests) == 1:
            return TransportResponse(
                302,
                redirect=True,
                headers={"Location": "https://cdn.example.org/final.pdf"},
            )
        return TransportResponse(200, PDF)

    runtime = ProviderRuntime.with_exchange(ProviderConfig(), MockExchange(send))
    async with (
        runtime,
        await runtime.acquire_document(
            DocumentRequest("https://papers.example.org/download")
        ) as document,
    ):
        assert document.filename == "final.pdf"
    assert requests == [
        "https://papers.example.org/download",
        "https://cdn.example.org/final.pdf",
    ]


async def test_pdf_download_cancellation_closes_the_response() -> None:
    started = asyncio.Event()
    closed = asyncio.Event()
    never = asyncio.Event()

    class BlockingResponse:
        status_code = 200
        redirect = False

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        async def aiter_bytes(self):
            started.set()
            yield PDF[:8]
            await never.wait()

        async def aclose(self) -> None:
            closed.set()

    def send(_request: TransportRequest) -> BlockingResponse:
        return BlockingResponse()

    runtime = ProviderRuntime.with_exchange(ProviderConfig(), MockExchange(send))
    async with runtime:
        task = asyncio.create_task(
            runtime.acquire_document(DocumentRequest("https://example.org/paper.pdf"))
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
