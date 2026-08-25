from __future__ import annotations

from typing import Any

import httpx2
from inquiro import ProviderConfig, ProviderRuntime
from inquiro.transport import MockExchange, TransportRequest, TransportResponse


def provider_config(settings: Any = None) -> ProviderConfig:
    return ProviderConfig(
        timeout_seconds=getattr(settings, "metadata_timeout_seconds", 10.0),
        max_response_bytes=getattr(settings, "metadata_max_response_bytes", 10_000_000),
        contact_email=getattr(settings, "metadata_contact_email", None),
        openalex_api_key=getattr(settings, "openalex_api_key", None),
        ncbi_api_key=getattr(settings, "ncbi_api_key", None),
        nasa_ads_token=getattr(settings, "nasa_ads_token", None),
        ieee_api_key=getattr(settings, "ieee_api_key", None),
    )


def mock_exchange(transport: httpx2.MockTransport) -> MockExchange:
    def send(request: TransportRequest) -> TransportResponse:
        response = transport.handler(
            httpx2.Request(
                "GET",
                request.url,
                params=request.params,
                headers=request.headers,
            )
        )
        assert isinstance(response, httpx2.Response)
        return TransportResponse(
            response.status_code,
            response.content,
            response.is_redirect,
            dict(response.headers),
        )

    return MockExchange(send)


def provider_runtime(
    *,
    settings: Any = None,
    transport: httpx2.MockTransport,
) -> ProviderRuntime:
    return ProviderRuntime.with_exchange(provider_config(settings), mock_exchange(transport))
