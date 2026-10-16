from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

from advanced_alchemy.utils.serialization import decode_json, encode_json
from starlette.routing import Router

from quirebase.web.app import create_app


def _empty_mcp_mount(*_args, **_kwargs):
    @asynccontextmanager
    async def lifespan():
        yield

    return SimpleNamespace(server=None, app=Router(), lifespan=lifespan)


def create_web_test_app(**kwargs):
    """Build the HTTP adapter without regenerating the separately tested MCP projection."""
    with patch("quirebase.web.app.create_mcp_http_mount", _empty_mcp_mount):
        return create_app(**kwargs)


def json_payload(value):
    """Serialize domain UUIDs as actual HTTP JSON strings."""
    return decode_json(encode_json(value))
