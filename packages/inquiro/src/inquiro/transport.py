from __future__ import annotations

import asyncio
import hashlib
import inspect
import tempfile
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import unquote, urljoin, urlsplit

import httpx2

from inquiro.models import (
    AcquiredDocument,
    InvalidPdfResponse,
    PdfAccessDenied,
    PdfNotAvailable,
    ProviderConfig,
    ProviderUnavailable,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping


@dataclass(frozen=True)
class TransportRequest:
    url: str
    params: Mapping[str, Any] | None = None
    headers: Mapping[str, str] | None = None


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    body: bytes = b""
    redirect: bool = False
    headers: Mapping[str, str] = field(default_factory=dict)

    async def aiter_bytes(self):
        yield self.body

    async def aclose(self) -> None:
        return None


class ExchangeResponse(Protocol):
    status_code: int
    redirect: bool
    headers: Mapping[str, str]

    def aiter_bytes(self): ...

    async def aclose(self) -> None: ...


class Exchange(Protocol):
    async def send(self, request: TransportRequest) -> ExchangeResponse: ...

    async def aclose(self) -> None: ...


@dataclass
class MockExchange:
    handler: Callable[[TransportRequest], ExchangeResponse | Awaitable[ExchangeResponse]]
    requests: list[TransportRequest] = field(default_factory=list)

    async def send(self, request: TransportRequest) -> ExchangeResponse:
        self.requests.append(request)
        response = self.handler(request)
        if inspect.isawaitable(response):
            response = await response
        return response

    async def aclose(self) -> None:
        return None


class HttpExchange:
    def __init__(self, config: ProviderConfig) -> None:
        agent = "Inquiro/0.1 scholarly provider runtime"
        if config.contact_email:
            agent += f" (mailto:{config.contact_email})"
        self._client = httpx2.AsyncClient(
            timeout=config.timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": agent, "Accept": "application/json, application/atom+xml"},
        )

    async def send(self, request: TransportRequest) -> ExchangeResponse:
        try:
            manager = self._client.stream(
                "GET",
                request.url,
                params=request.params,
                headers=request.headers,
            )
            response = await manager.__aenter__()
        except httpx2.HTTPError as error:
            raise ProviderUnavailable("metadata provider request failed") from error
        return _HttpExchangeResponse(manager, response)

    async def aclose(self) -> None:
        await self._client.aclose()


class RemoteNotFound(Exception):
    pass


class _HttpExchangeResponse:
    def __init__(self, manager: Any, response: httpx2.Response) -> None:
        self._manager = manager
        self._response = response
        self.status_code = response.status_code
        self.redirect = response.is_redirect
        self.headers: Mapping[str, str] = dict(response.headers)

    async def aiter_bytes(self):
        try:
            async for chunk in self._response.aiter_bytes():
                yield chunk
        except httpx2.HTTPError as error:
            raise ProviderUnavailable("metadata provider request failed") from error

    async def aclose(self) -> None:
        await self._manager.__aexit__(None, None, None)


class BoundedTransport:
    def __init__(self, config: ProviderConfig, exchange: Exchange) -> None:
        self._config = config
        self._exchange = exchange

    async def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        response = await self._exchange.send(TransportRequest(url, params, headers))
        try:
            if response.status_code == 404:
                raise RemoteNotFound
            if response.status_code == 429:
                raise ProviderUnavailable("metadata provider rate limit was reached")
            if response.redirect or 300 <= response.status_code < 400:
                raise ProviderUnavailable("metadata provider returned an unexpected redirect")
            if response.status_code >= 400:
                raise ProviderUnavailable("metadata provider request failed")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self._config.max_response_bytes:
                    raise ProviderUnavailable("metadata response exceeded the size limit")
            return bytes(body)
        finally:
            await response.aclose()

    async def download_pdf(
        self,
        url: str,
        *,
        filename: str | None = None,
        provider: str | None = None,
    ) -> AcquiredDocument:
        current_url = url
        for _redirect in range(6):
            response = await self._exchange.send(
                TransportRequest(current_url, headers={"Accept": "application/pdf"})
            )
            try:
                if response.redirect or 300 <= response.status_code < 400:
                    location = _header(response.headers, "location")
                    if not location:
                        raise ProviderUnavailable("PDF provider returned an invalid redirect")
                    current_url = urljoin(current_url, location)
                    parsed = urlsplit(current_url)
                    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                        raise ProviderUnavailable("PDF provider returned an invalid redirect")
                    continue
                if response.status_code == 404:
                    raise PdfNotAvailable("PDF was not found")
                if response.status_code in {401, 403}:
                    raise PdfAccessDenied("PDF access was denied")
                if response.status_code == 429:
                    raise ProviderUnavailable("PDF provider rate limit was reached")
                if response.status_code >= 400:
                    raise ProviderUnavailable("PDF provider request failed")
                return await self._read_pdf(
                    response,
                    current_url,
                    filename=filename,
                    provider=provider,
                )
            finally:
                await response.aclose()
        raise ProviderUnavailable("PDF provider returned too many redirects")

    async def _read_pdf(
        self,
        response: ExchangeResponse,
        url: str,
        *,
        filename: str | None,
        provider: str | None,
    ) -> AcquiredDocument:
        # The returned AcquiredDocument takes ownership and closes this stream.
        stream = tempfile.SpooledTemporaryFile(  # ruff: ignore[open-file-with-context-handler]
            max_size=5_000_000,
            mode="w+b",
        )
        digest = hashlib.sha256()
        size = 0
        try:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self._config.max_document_bytes:
                    raise InvalidPdfResponse("PDF exceeded the size limit")
                await asyncio.to_thread(stream.write, chunk)
                digest.update(chunk)
            await asyncio.to_thread(stream.seek, 0)
            if b"%PDF-" not in await asyncio.to_thread(stream.read, 1024):
                raise InvalidPdfResponse("PDF provider returned a non-PDF response")
            await asyncio.to_thread(stream.seek, 0)
        except BaseException:
            await asyncio.to_thread(stream.close)
            raise
        return AcquiredDocument(
            stream=stream,
            filename=filename or self._pdf_filename(url),
            media_type="application/pdf",
            size_bytes=size,
            sha256=digest.hexdigest(),
            provider=provider,
        )

    @staticmethod
    def _pdf_filename(url: str) -> str:
        decoded = unquote(urlsplit(url).path.rsplit("/", 1)[-1]).replace("\\", "/")
        basename = decoded.rsplit("/", 1)[-1]
        filename = "".join(
            character
            for character in basename
            if character.isprintable() and character not in '<>:"/\\|?*'
        ).strip(" .")
        return filename if filename.lower().endswith(".pdf") else "downloaded.pdf"

    async def aclose(self) -> None:
        await self._exchange.aclose()


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Read a transport header using HTTP's case-insensitive field-name rules."""
    value = headers.get(name)
    if value is not None:
        return value
    folded = name.casefold()
    return next((candidate for key, candidate in headers.items() if key.casefold() == folded), None)
