from __future__ import annotations

import base64
import hashlib
import re

import pytest
from test_http import authenticated_async_client

from quirebase.web.app import _frontend_directory


@pytest.mark.anyio
async def test_frontend_routes_return_the_static_svelte_application(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    if not (_frontend_directory() / "index.html").is_file():
        pytest.skip("frontend build is not available")
    try:
        library = await client.get("/library", headers={"Accept": "text/html"})
        deep_link = await client.get("/item/example/metadata", headers={"Accept": "text/html"})
        theme_bootstrap = await client.get("/theme.js")
        api = await client.get(f"/api/v1/workspaces/{item.workspace_id}/items")
    finally:
        await client.aclose()

    assert library.status_code == 200
    assert deep_link.status_code == 200
    assert "Quirebase research library" in library.text
    assert "_app/immutable" in deep_link.text
    csp = library.headers["content-security-policy"]
    assert "sha256-" in csp
    inline_scripts = [
        body
        for attributes, body in re.findall(
            r"<script([^>]*)>(.*?)</script>", library.text, flags=re.DOTALL
        )
        if "src=" not in attributes
    ]
    assert inline_scripts
    for script in inline_scripts:
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in csp
    assert '<script src="/theme.js"></script>' in library.text
    assert theme_bootstrap.status_code == 200
    assert theme_bootstrap.headers["content-type"].split(";", 1)[0] in {
        "application/javascript",
        "text/javascript",
    }
    assert api.headers["content-type"].startswith("application/json")


@pytest.mark.anyio
async def test_cookie_authenticated_api_responses_are_never_shared_cached(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        session = await client.get("/api/v1/session")
        library = await client.get(f"/api/v1/workspaces/{item.workspace_id}/items")
    finally:
        await client.aclose()

    assert session.headers["cache-control"] == "private, no-store"
    assert library.headers["cache-control"] == "private, no-store"


@pytest.mark.anyio
async def test_anonymous_session_bootstrap_is_never_shared_cached(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    if not (_frontend_directory() / "index.html").is_file():
        pytest.skip("frontend build is not available")
    client.cookies.clear()
    try:
        session = await client.get("/api/v1/session")
    finally:
        await client.aclose()

    assert session.status_code == 200
    assert session.json()["authenticated"] is False
    assert session.headers["cache-control"] == "private, no-store"


@pytest.mark.anyio
async def test_frontend_fallback_only_handles_browser_navigation(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    if not (_frontend_directory() / "index.html").is_file():
        pytest.skip("frontend build is not available")
    try:
        navigation = await client.get(
            "/missing-workspace-route",
            headers={"Accept": "text/html"},
        )
        missing_asset = await client.get(
            "/_app/immutable/missing.js",
            headers={"Accept": "*/*"},
        )
    finally:
        await client.aclose()

    assert navigation.status_code == 200
    assert "Quirebase research library" in navigation.text
    assert missing_asset.status_code == 404


@pytest.mark.anyio
async def test_vite_managed_pdfium_asset_is_served_immutably(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    frontend = _frontend_directory()
    wasm_files = tuple((frontend / "_app" / "immutable" / "assets").glob("pdfium.*.wasm"))
    if not wasm_files:
        pytest.skip("frontend PDFium asset is not available")
    assert len(wasm_files) == 1
    asset_path = wasm_files[0].relative_to(frontend).as_posix()
    try:
        response = await client.get(f"/{asset_path}")
    finally:
        await client.aclose()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/wasm"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.content[:4] == b"\x00asm"
