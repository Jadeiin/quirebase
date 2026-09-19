from __future__ import annotations

import asyncio
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from typing import TYPE_CHECKING

import pytest
from inquiro.models import ProviderUnavailable
from inquiro.transport import HttpExchange, TransportRequest
from inquiro_provider_helpers import provider_config

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.anyio


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    slow_started = Event()

    def log_message(self, format: str, *args: object) -> None:
        return None

    def do_GET(self) -> None:
        if self.path.startswith("/ok"):
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/truncated"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "64")
            self.end_headers()
            self.wfile.write(b'{"partial"')
            self.wfile.flush()
            self.close_connection = True
        elif self.path.startswith("/slow"):
            self.slow_started.set()
            time.sleep(30)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@pytest.fixture(autouse=True)
def _clear_proxy_environment(monkeypatch):
    """Keep these loopback tests hermetic when the environment defines a proxy.

    httpx builds its proxy transport while the client is constructed, so an ambient
    ``ALL_PROXY`` without ``socksio`` fails before a request reaches 127.0.0.1 even when
    ``NO_PROXY`` covers it.
    """
    for name in (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def base_url() -> Iterator[str]:
    _Handler.slow_started.clear()
    server = _Server(("127.0.0.1", 0), _Handler)
    server.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_http_exchange_streams_a_response_and_stays_usable(base_url: str):
    exchange = HttpExchange(provider_config())
    try:
        response = await exchange.send(TransportRequest(f"{base_url}/ok"))
        try:
            assert response.status_code == 200
            assert response.redirect is False
            assert response.headers["content-type"] == "application/json"
            body = b"".join([chunk async for chunk in response.aiter_bytes()])
            assert body == b'{"ok": true}'
        finally:
            await response.aclose()

        follow_up = await exchange.send(TransportRequest(f"{base_url}/ok"))
        await follow_up.aclose()
    finally:
        await exchange.aclose()


async def test_http_exchange_reports_a_broken_stream_as_provider_unavailable(base_url: str):
    exchange = HttpExchange(provider_config())
    try:
        response = await exchange.send(TransportRequest(f"{base_url}/truncated"))
        try:
            with pytest.raises(ProviderUnavailable):
                async for _chunk in response.aiter_bytes():
                    pass
        finally:
            await response.aclose()

        follow_up = await exchange.send(TransportRequest(f"{base_url}/ok"))
        try:
            body = b"".join([chunk async for chunk in follow_up.aiter_bytes()])
            assert body == b'{"ok": true}'
        finally:
            await follow_up.aclose()
    finally:
        await exchange.aclose()


async def test_http_exchange_cancels_a_pending_request_without_wedging_the_client(base_url: str):
    exchange = HttpExchange(provider_config())
    try:
        task = asyncio.create_task(exchange.send(TransportRequest(f"{base_url}/slow")))
        assert await asyncio.to_thread(_Handler.slow_started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        follow_up = await exchange.send(TransportRequest(f"{base_url}/ok"))
        try:
            body = b"".join([chunk async for chunk in follow_up.aiter_bytes()])
            assert body == b'{"ok": true}'
        finally:
            await follow_up.aclose()
    finally:
        await exchange.aclose()
