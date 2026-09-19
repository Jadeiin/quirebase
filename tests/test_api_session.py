from __future__ import annotations

import httpx2
import pytest
from sqlalchemy import select
from test_http import authenticated_async_client

from quirebase.accounts import create_api_token, create_login_session
from quirebase.core.crypto import hash_password
from quirebase.core.database import get_db
from quirebase.models import LoginSession, User
from quirebase.web.app import create_app


@pytest.mark.anyio
async def test_login_session_can_use_safe_api_routes(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.get("/api/v1/items")
        assert response.status_code == 200
        assert response.json()["total"] == 1
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_session_api_mutations_require_an_exact_origin(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        missing = await client.post(
            f"/api/v1/items/{item.id}/tags",
            headers={"Origin": ""},
            json={"name": "Missing origin"},
        )
        cross_origin = await client.post(
            f"/api/v1/items/{item.id}/tags",
            headers={"Origin": "https://attacker.example"},
            json={"name": "Cross origin"},
        )
        same_origin = await client.post(
            f"/api/v1/items/{item.id}/tags",
            headers={"Origin": "http://testserver"},
            json={"name": "Same origin"},
        )

        assert missing.status_code == 403
        assert cross_origin.status_code == 403
        assert same_origin.status_code == 200
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_session_api_uses_configured_external_origin_behind_tls_proxy(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    monkeypatch.setenv("QUIREBASE_EXTERNAL_ORIGIN", "https://library.example")
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        accepted = await client.post(
            f"/api/v1/items/{item.id}/tags",
            headers={"Origin": "https://library.example"},
            json={"name": "Proxied request"},
        )
        internal_origin = await client.post(
            f"/api/v1/items/{item.id}/tags",
            headers={"Origin": "http://testserver"},
            json={"name": "Internal origin"},
        )

        assert accepted.status_code == 200
        assert internal_origin.status_code == 403
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_authorization_header_never_falls_back_to_login_session(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.get(
            "/api/v1/items",
            headers={"Authorization": "Bearer invalid"},
        )
        assert response.status_code == 401
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_session_bootstrap_returns_the_browser_identity(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.get("/api/v1/session")
        assert response.status_code == 200
        assert response.json() == {
            "authenticated": True,
            "user": {
                "id": response.json()["user"]["id"],
                "username": "reader",
                "role": "member",
            },
        }
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_login_and_logout_use_json_and_same_origin_policy(async_db, async_session_factory):
    async_db.add(User(username="alice", password_hash=hash_password("correct horse battery")))
    await async_db.commit()
    test_app = create_app(mcp_session_factory=async_session_factory)

    async def override_db():  # ruff: ignore[unused-async] - FastAPI yield dependency
        yield async_db

    test_app.dependency_overrides[get_db] = override_db
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=test_app),
        base_url="http://testserver",
    ) as client:
        missing = await client.post(
            "/api/v1/session",
            json={"username": "alice", "password": "correct horse battery"},
        )
        cross_origin = await client.post(
            "/api/v1/session",
            headers={"Origin": "https://attacker.example"},
            json={"username": "alice", "password": "correct horse battery"},
        )
        accepted = await client.post(
            "/api/v1/session",
            headers={"Origin": "http://testserver"},
            json={"username": "alice", "password": "correct horse battery"},
        )
        bootstrap = await client.get("/api/v1/session")
        logged_out = await client.delete("/api/v1/session", headers={"Origin": "http://testserver"})

    assert missing.status_code == 403
    assert cross_origin.status_code == 403
    assert accepted.status_code == 200
    assert "httponly" in accepted.headers["set-cookie"].casefold()
    assert bootstrap.json()["user"]["username"] == "alice"
    assert logged_out.status_code == 204


@pytest.mark.anyio
async def test_logout_rejects_a_cookie_owned_by_another_authenticated_user(
    async_db, async_session_factory
):
    bearer_user = User(username="bearer-user", password_hash="unused")
    cookie_user = User(username="cookie-user", password_hash="unused")
    async_db.add_all([bearer_user, cookie_user])
    await async_db.commit()
    grant = await create_api_token(async_db, bearer_user, "Mixed credentials", expires_in_days=1)
    login, raw_session = await create_login_session(async_db, cookie_user, session_days=1)
    login_id = login.id
    test_app = create_app(mcp_session_factory=async_session_factory)

    async def override_db():  # ruff: ignore[unused-async] - FastAPI yield dependency
        yield async_db

    test_app.dependency_overrides[get_db] = override_db
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=test_app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as client:
        client.cookies.set("quirebase_session", raw_session)
        response = await client.delete(
            "/api/v1/session", headers={"Authorization": f"Bearer {grant.raw_token}"}
        )

    assert response.status_code == 401
    assert (
        await async_db.scalar(select(LoginSession).where(LoginSession.id == login_id)) is not None
    )
