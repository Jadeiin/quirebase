from __future__ import annotations

import hashlib
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
    from collections.abc import Callable, Mapping


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

    def iter_bytes(self):
        yield self.body

    def close(self) -> None:
        return None


class ExchangeResponse(Protocol):
    status_code: int
    redirect: bool
    headers: Mapping[str, str]

    def iter_bytes(self): ...

    def close(self) -> None: ...


class Exchange(Protocol):
    def send(self, request: TransportRequest) -> ExchangeResponse: ...

    def close(self) -> None: ...


@dataclass
class MockExchange:
    handler: Callable[[TransportRequest], TransportResponse]
    requests: list[TransportRequest] = field(default_factory=list)

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        return self.handler(request)

    def close(self) -> None:
        return None


class HttpExchange:
    def __init__(self, config: ProviderConfig) -> None:
        agent = "Inquiro/0.1 scholarly provider runtime"
        if config.contact_email:
            agent += f" (mailto:{config.contact_email})"
        self._client = httpx2.Client(
            timeout=config.timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": agent, "Accept": "application/json, application/atom+xml"},
        )

    def send(self, request: TransportRequest) -> ExchangeResponse:
        try:
            manager = self._client.stream(
                "GET",
                request.url,
                params=request.params,
                headers=request.headers,
            )
            response = manager.__enter__()
        except httpx2.HTTPError as error:
            raise ProviderUnavailable("metadata provider request failed") from error
        return _HttpExchangeResponse(manager, response)

    def close(self) -> None:
        self._client.close()


class RemoteNotFound(Exception):
    pass


class _HttpExchangeResponse:
    def __init__(self, manager: Any, response: httpx2.Response) -> None:
        self._manager = manager
        self._response = response
        self.status_code = response.status_code
        self.redirect = response.is_redirect
        self.headers: Mapping[str, str] = dict(response.headers)

    def iter_bytes(self):
        try:
            yield from self._response.iter_bytes()
        except httpx2.HTTPError as error:
            raise ProviderUnavailable("metadata provider request failed") from error

    def close(self) -> None:
        self._manager.__exit__(None, None, None)


class BoundedTransport:
    def __init__(self, config: ProviderConfig, exchange: Exchange) -> None:
        self._config = config
        self._exchange = exchange

    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        response = self._exchange.send(TransportRequest(url, params, headers))
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
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > self._config.max_response_bytes:
                    raise ProviderUnavailable("metadata response exceeded the size limit")
            return bytes(body)
        finally:
            response.close()

    def download_pdf(
        self,
        url: str,
        *,
        filename: str | None = None,
        provider: str | None = None,
    ) -> AcquiredDocument:
        current_url = url
        for _redirect in range(6):
            response = self._exchange.send(
                TransportRequest(current_url, headers={"Accept": "application/pdf"})
            )
            try:
                if response.redirect or 300 <= response.status_code < 400:
                    location = response.headers.get("location")
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
                return self._read_pdf(
                    response,
                    current_url,
                    filename=filename,
                    provider=provider,
                )
            finally:
                response.close()
        raise ProviderUnavailable("PDF provider returned too many redirects")

    def _read_pdf(
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
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self._config.max_document_bytes:
                    raise InvalidPdfResponse("PDF exceeded the size limit")
                stream.write(chunk)
                digest.update(chunk)
            stream.seek(0)
            if b"%PDF-" not in stream.read(1024):
                raise InvalidPdfResponse("PDF provider returned a non-PDF response")
            stream.seek(0)
        except Exception:
            stream.close()
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

    def close(self) -> None:
        self._exchange.close()
