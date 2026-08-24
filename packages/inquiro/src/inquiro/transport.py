from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import httpx2

from inquiro.models import ProviderConfig, ProviderUnavailable

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

    def iter_bytes(self):
        yield self.body

    def close(self) -> None:
        return None


class ExchangeResponse(Protocol):
    status_code: int
    redirect: bool

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

    def close(self) -> None:
        self._exchange.close()
