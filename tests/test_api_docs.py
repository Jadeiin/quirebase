from __future__ import annotations

import base64
import hashlib
import re

import pytest
from test_http import authenticated_async_client

DOCUMENTATION_PATHS = ("/docs", "/docs/oauth2-redirect", "/redoc")
_SCRIPT_PATTERN = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.DOTALL | re.IGNORECASE)


def inline_script_hashes(html: str) -> list[str]:
    return [
        f"'sha256-{base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()}'"
        for attributes, body in _SCRIPT_PATTERN.findall(html)
        if "src=" not in attributes
    ]


@pytest.mark.anyio
async def test_documentation_pages_receive_a_docs_specific_csp(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        documentation = {
            path: await client.get(path, headers={"Accept": "text/html"})
            for path in DOCUMENTATION_PATHS
        }
        library = await client.get("/library", headers={"Accept": "text/html"})
    finally:
        await client.aclose()

    application_csp = library.headers["content-security-policy"]
    assert "cdn.jsdelivr.net" not in application_csp
    for page in documentation.values():
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        csp = page.headers["content-security-policy"]
        assert csp != application_csp
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "wasm-unsafe-eval" not in csp
        assert "blob:" not in csp
        for digest in inline_script_hashes(page.text):
            assert digest in csp


@pytest.mark.anyio
async def test_documentation_pages_exempt_their_external_assets(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        swagger = await client.get("/docs", headers={"Accept": "text/html"})
        redoc = await client.get("/redoc", headers={"Accept": "text/html"})
    finally:
        await client.aclose()

    assert "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5" in swagger.text
    assert "https://fastapi.tiangolo.com/img/favicon.png" in swagger.text
    swagger_csp = swagger.headers["content-security-policy"]
    assert "script-src 'self' https://cdn.jsdelivr.net" in swagger_csp
    assert "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net" in swagger_csp
    assert "img-src 'self' data: https://fastapi.tiangolo.com" in swagger_csp

    assert "https://cdn.jsdelivr.net/npm/redoc@2" in redoc.text
    assert "https://fonts.googleapis.com" in redoc.text
    redoc_csp = redoc.headers["content-security-policy"]
    assert "https://fonts.googleapis.com" in redoc_csp
    assert "font-src 'self' data: https://fonts.gstatic.com" in redoc_csp


@pytest.mark.anyio
async def test_api_and_openapi_responses_do_not_receive_the_spa_csp(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        openapi = await client.get("/openapi.json")
        session = await client.get("/api/v1/session")
        library = await client.get("/library", headers={"Accept": "text/html"})
    finally:
        await client.aclose()

    for response in (openapi, session):
        assert "content-security-policy" not in response.headers
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "same-origin"
        assert response.headers["x-frame-options"] == "DENY"

    assert "content-security-policy" in library.headers
