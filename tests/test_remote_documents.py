from __future__ import annotations

from unittest.mock import AsyncMock

import httpx2
import pytest

from quirebase.core.errors import SizeLimitExceeded, ValidationFailure
from quirebase.documents import acquire_remote_attachment
from quirebase.documents import remote as remote_documents


def mock_remote_client(monkeypatch, handler):
    client_type = httpx2.AsyncClient
    transport = httpx2.MockTransport(handler)

    monkeypatch.setattr(
        remote_documents,
        "_resolve_addresses",
        AsyncMock(return_value=("8.8.8.8",)),
    )
    monkeypatch.setattr(
        remote_documents.httpx2,
        "AsyncClient",
        lambda **options: client_type(transport=transport, **options),
    )


@pytest.mark.anyio
async def test_remote_attachment_is_bounded_and_exposes_download_metadata(monkeypatch):
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == "https://8.8.8.8/files/supplement"
        assert request.headers["host"] == "publisher.example"
        return httpx2.Response(
            200,
            headers={
                "Content-Disposition": 'attachment; filename="data.zip"',
                "Content-Type": "application/zip",
            },
            content=b"archive",
        )

    mock_remote_client(monkeypatch, handler)

    async with acquire_remote_attachment(
        "https://publisher.example/files/supplement", 1024
    ) as attachment:
        assert attachment.filename == "data.zip"
        assert attachment.media_type == "application/zip"
        assert b"".join([chunk async for chunk in attachment.content]) == b"archive"


@pytest.mark.anyio
async def test_remote_attachment_rejects_oversized_content(monkeypatch):
    mock_remote_client(
        monkeypatch,
        lambda _request: httpx2.Response(200, content=b"too large"),
    )

    with pytest.raises(SizeLimitExceeded, match="size limit"):
        async with acquire_remote_attachment("https://publisher.example/file", 3):
            pass


@pytest.mark.anyio
async def test_remote_attachment_requires_an_http_source():
    with pytest.raises(ValidationFailure, match="HTTP or HTTPS"):
        async with acquire_remote_attachment("file:///private/report.pdf", 1024):
            pass


@pytest.mark.parametrize(
    "source",
    [
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/admin",
    ],
)
@pytest.mark.anyio
async def test_remote_attachment_rejects_non_public_literal_addresses(source):
    with pytest.raises(ValidationFailure, match="public addresses"):
        async with acquire_remote_attachment(source, 1024):
            pass


@pytest.mark.anyio
async def test_remote_attachment_revalidates_redirect_targets(monkeypatch):
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(302, headers={"Location": "http://127.0.0.1/private"})

    mock_remote_client(monkeypatch, handler)

    with pytest.raises(ValidationFailure, match="public addresses"):
        async with acquire_remote_attachment("https://publisher.example/file", 1024):
            pass

    assert len(requests) == 1


@pytest.mark.anyio
async def test_remote_attachment_rejects_dns_names_with_any_non_public_address(monkeypatch):
    monkeypatch.setattr(
        remote_documents,
        "_resolve_addresses",
        AsyncMock(return_value=("8.8.8.8", "10.0.0.8")),
    )

    with pytest.raises(ValidationFailure, match="public addresses"):
        async with acquire_remote_attachment("https://publisher.example/file", 1024):
            pass
