from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from quirebase import cli
from quirebase.accounts import (
    API_TOKEN_PREFIX,
    create_api_token,
    list_api_tokens,
    revoke_api_token,
    verify_api_token,
)
from quirebase.accounts.sessions import create_login_session, get_login_session_by_token
from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.database import get_db
from quirebase.core.errors import ValidationFailure
from quirebase.mcp import ApiTokenVerifier
from quirebase.models import ApiToken, AuditEvent, User
from quirebase.web.app import create_app

runner = CliRunner()


@asynccontextmanager
async def mcp_client(test_app):
    async with (
        test_app.router.lifespan_context(test_app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=test_app), base_url="http://testserver"
        ) as client,
    ):
        yield client


async def account_client(db, session_factory, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    user = User(username="reader", password_hash="unused")
    db.add(user)
    await db.flush()
    raw_token = "test-session-token"
    login, _generated = await create_login_session(db, user, session_days=1)
    login.token_hash = token_hash(raw_token)
    login.csrf_token = "test-csrf"
    await db.commit()

    test_app = create_app(mcp_session_factory=session_factory)

    async def override_db():
        await asyncio.sleep(0)
        yield db

    test_app.dependency_overrides[get_db] = override_db
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=test_app),
        base_url="http://testserver",
        headers={"Accept-Language": "zh-CN,zh;q=0.9"},
    )
    client.cookies.set(get_settings().session_cookie, raw_token)
    return client, user


@pytest.mark.anyio
async def test_api_token_is_shown_once_and_stored_as_a_hash(async_db):
    db = async_db
    user = User(username="token-owner", password_hash="unused")
    db.add(user)
    await db.commit()

    grant = await create_api_token(db, user, "Research client", expires_in_days=30)
    stored = await db.get(ApiToken, grant.token_id)
    verified = await verify_api_token(db, grant.raw_token)

    assert grant.raw_token.startswith(API_TOKEN_PREFIX)
    assert stored is not None
    assert stored.token_hash == token_hash(grant.raw_token)
    assert grant.raw_token not in stored.token_hash
    assert verified is not None
    assert verified.user_id == user.id
    assert (await list_api_tokens(db, user))[0].name == "Research client"
    event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.api_token.create"))
    assert event is not None and event.actor_id == user.id


@pytest.mark.anyio
async def test_revoked_expired_and_inactive_user_tokens_are_rejected(async_db):
    db = async_db
    user = User(username="revoked-token-owner", password_hash="unused")
    db.add(user)
    await db.commit()
    revoked = await create_api_token(db, user, "Revoked", expires_in_days=1)
    await revoke_api_token(db, user, revoked.token_id)
    assert await verify_api_token(db, revoked.raw_token) is None

    expired = await create_api_token(db, user, "Expired", expires_in_days=1)
    record = await db.get(ApiToken, expired.token_id)
    assert record is not None
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    assert await verify_api_token(db, expired.raw_token) is None

    inactive = await create_api_token(db, user, "Inactive", expires_in_days=1)
    user.active = False
    await db.commit()
    assert await verify_api_token(db, inactive.raw_token) is None


@pytest.mark.anyio
async def test_token_expiry_preserves_timezone_offsets_with_aware_and_naive_datetimes(async_db):
    db = async_db
    from datetime import timezone

    tz_plus_8 = timezone(timedelta(hours=8))
    tz_minus_5 = timezone(timedelta(hours=-5))

    user = User(username="tz-token-owner", password_hash="unused")
    db.add(user)
    await db.commit()

    grant = await create_api_token(db, user, "TZ Token", expires_in_days=1)
    record = await db.get(ApiToken, grant.token_id)
    assert record is not None

    # An expiry 5 minutes ago in UTC, represented with +08:00 offset
    past_instant = datetime.now(UTC) - timedelta(minutes=5)
    record.expires_at = past_instant.astimezone(tz_plus_8)
    await db.commit()

    summary = (await list_api_tokens(db, user))[0]
    assert summary.status == "expired"
    assert await verify_api_token(db, grant.raw_token) is None

    # An expiry 10 minutes in the future in UTC, represented with -05:00 offset
    future_instant = datetime.now(UTC) + timedelta(minutes=10)
    record.expires_at = future_instant.astimezone(tz_minus_5)
    await db.commit()

    active_summary = (await list_api_tokens(db, user))[0]
    assert active_summary.status == "active"
    verified = await verify_api_token(db, grant.raw_token)
    assert verified is not None
    assert verified.expires_at.tzinfo == UTC
    assert int(verified.expires_at.timestamp()) == int(future_instant.timestamp())

    # Naive datetime (simulating SQLite return)
    naive_future = datetime.now(UTC) + timedelta(minutes=15)
    record.expires_at = naive_future.replace(tzinfo=None)
    await db.commit()
    naive_verified = await verify_api_token(db, grant.raw_token)
    assert naive_verified is not None
    assert naive_verified.expires_at.tzinfo == UTC


@pytest.mark.anyio
async def test_login_session_expiry_preserves_timezone_offset(async_db):
    db = async_db
    from datetime import timezone

    user = User(username="tz-session-owner", password_hash="unused")
    db.add(user)
    await db.commit()
    login, raw_token = await create_login_session(db, user, session_days=1)
    login.expires_at = (datetime.now(UTC) - timedelta(minutes=5)).astimezone(
        timezone(timedelta(hours=8))
    )
    await db.commit()

    assert await get_login_session_by_token(db, raw_token) is None


@pytest.mark.anyio
async def test_api_token_lifetime_and_name_are_bounded(async_db):
    db = async_db
    user = User(username="bounded-token-owner", password_hash="unused")
    db.add(user)
    await db.commit()

    with pytest.raises(ValidationFailure, match="name"):
        await create_api_token(db, user, " ", expires_in_days=30)
    with pytest.raises(ValidationFailure, match="120"):
        await create_api_token(db, user, "x" * 121, expires_in_days=30)
    with pytest.raises(ValidationFailure, match="1-365"):
        await create_api_token(db, user, "Too long", expires_in_days=366)


@pytest.mark.anyio
async def test_mcp_verifier_redacts_raw_token_and_returns_no_scopes(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="verifier-owner", password_hash="unused")
    db.add(user)
    await db.commit()
    grant = await create_api_token(db, user, "Verifier", expires_in_days=30)
    verifier = ApiTokenVerifier(async_session_factory)

    access = await verifier.verify_token(grant.raw_token)

    assert access is not None
    assert access.token == "<redacted>"
    assert access.subject == user.id
    assert access.client_id == f"quirebase-api-token:{grant.token_id}"
    assert access.scopes == []


@pytest.mark.anyio
async def test_mcp_http_accepts_only_a_valid_bearer_api_token(async_db, async_session_factory):
    db = async_db
    user = User(username="http-token-owner", password_hash="unused")
    db.add(user)
    await db.commit()
    grant = await create_api_token(db, user, "HTTP", expires_in_days=30)
    test_app = create_app(mcp_session_factory=async_session_factory)
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "quirebase-test", "version": "1"},
        },
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    async with mcp_client(test_app) as client:
        assert (await client.post("/mcp/", json=initialize, headers=headers)).status_code == 401
        assert (
            await client.post(f"/mcp/?token={grant.raw_token}", json=initialize, headers=headers)
        ).status_code == 401
        invalid = await client.post(
            "/mcp/",
            json=initialize,
            headers={**headers, "Authorization": "Bearer invalid"},
        )
        accepted = await client.post(
            "/mcp/",
            json=initialize,
            headers={**headers, "Authorization": f"Bearer {grant.raw_token}"},
        )
        called = await client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "library.search", "arguments": {"query": ""}},
            },
            headers={**headers, "Authorization": f"Bearer {grant.raw_token}"},
        )

    assert invalid.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["result"]["serverInfo"]["name"] == "Quirebase"
    assert called.status_code == 200


@pytest.mark.anyio
async def test_mcp_http_rejects_malformed_arguments_without_protocol_audit(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="invalid-mcp-arguments", password_hash="unused")
    db.add(user)
    await db.commit()
    grant = await create_api_token(db, user, "Malformed call", expires_in_days=30)
    test_app = create_app(mcp_session_factory=async_session_factory)
    headers = {
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {grant.raw_token}",
        "Content-Type": "application/json",
    }

    async with mcp_client(test_app) as client:
        response = await client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "library.get_item", "arguments": {}},
            },
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["result"]["isError"] is True
    events = list(
        (await db.scalars(select(AuditEvent).where(AuditEvent.target_id == grant.token_id))).all()
    )
    assert [event.action for event in events] == ["auth.api_token.create"]


@pytest.mark.parametrize(
    ("allowed_hosts", "host"),
    [
        ("localhost,127.0.0.1,testserver", "localhost:8000"),
        ("*.example.com", "research.example.com:8443"),
        ("*", "arbitrary.example:9000"),
    ],
)
@pytest.mark.anyio
async def test_mcp_http_preserves_web_allowed_host_semantics(
    async_db, async_session_factory, monkeypatch, allowed_hosts, host
):
    db = async_db
    user = User(username=f"host-{host}", password_hash="unused")
    db.add(user)
    await db.commit()
    grant = await create_api_token(db, user, "HTTP host", expires_in_days=30)
    monkeypatch.setenv("QUIREBASE_ALLOWED_HOSTS", allowed_hosts)
    get_settings.cache_clear()
    test_app = create_app(mcp_session_factory=async_session_factory)
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "host-test", "version": "1"},
        },
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {grant.raw_token}",
        "Host": host,
    }

    try:
        async with mcp_client(test_app) as client:
            response = await client.post("/mcp/", json=initialize, headers=headers)
        assert response.status_code == 200
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("configured_origins", "origin", "expected_status"),
    [
        ("", "https://attacker.example", 403),
        ("https://client.example", "https://client.example", 200),
        ("http://localhost:*", "http://localhost:4310", 200),
        ("https://client.example", "https://other.example", 403),
    ],
)
@pytest.mark.anyio
async def test_mcp_http_validates_browser_origins_with_wildcard_hosts(
    async_db,
    async_session_factory,
    monkeypatch,
    configured_origins,
    origin,
    expected_status,
):
    db = async_db
    user = User(username=f"origin-{expected_status}-{origin}", password_hash="unused")
    db.add(user)
    await db.commit()
    grant = await create_api_token(db, user, "Browser MCP", expires_in_days=30)
    monkeypatch.setenv("QUIREBASE_ALLOWED_HOSTS", "*")
    monkeypatch.setenv("QUIREBASE_MCP_ALLOWED_ORIGINS", configured_origins)
    get_settings.cache_clear()
    test_app = create_app(mcp_session_factory=async_session_factory)
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "origin-test", "version": "1"},
        },
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {grant.raw_token}",
        "Host": "internal.quirebase:8000",
        "Origin": origin,
    }

    try:
        async with mcp_client(test_app) as client:
            response = await client.post("/mcp/", json=initialize, headers=headers)
        assert response.status_code == expected_status
        if expected_status == 200:
            assert response.headers["access-control-allow-origin"] == origin
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_mcp_http_handles_browser_cors_preflight_before_authentication(
    async_session_factory, monkeypatch
):
    monkeypatch.setenv("QUIREBASE_ALLOWED_HOSTS", "*")
    monkeypatch.setenv("QUIREBASE_MCP_ALLOWED_ORIGINS", "https://client.example")
    get_settings.cache_clear()
    test_app = create_app(mcp_session_factory=async_session_factory)

    try:
        async with mcp_client(test_app) as client:
            response = await client.options(
                "/mcp/",
                headers={
                    "Host": "internal.quirebase:8000",
                    "Origin": "https://client.example",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": (
                        "authorization,content-type,mcp-protocol-version,mcp-session-id"
                    ),
                },
            )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://client.example"
        assert "POST" in response.headers["access-control-allow-methods"]
        allowed_headers = response.headers["access-control-allow-headers"].lower()
        assert "authorization" in allowed_headers
        assert "mcp-protocol-version" in allowed_headers
        assert "mcp-session-id" in allowed_headers
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_mcp_http_rejects_untrusted_origin_before_authentication(
    async_session_factory, monkeypatch
):
    monkeypatch.setenv("QUIREBASE_ALLOWED_HOSTS", "*")
    monkeypatch.delenv("QUIREBASE_MCP_ALLOWED_ORIGINS", raising=False)
    get_settings.cache_clear()
    test_app = create_app(mcp_session_factory=async_session_factory)

    try:
        async with mcp_client(test_app) as client:
            response = await client.post(
                "/mcp/",
                json={},
                headers={
                    "Content-Type": "application/json",
                    "Host": "internal.quirebase:8000",
                    "Origin": "https://attacker.example",
                },
            )
        assert response.status_code == 403
        assert response.text == "Invalid Origin header"
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_api_token_cli_creates_lists_and_revokes(
    async_db, async_session_factory, monkeypatch
):
    db = async_db
    user = User(username="cli-token-owner", password_hash="unused")
    db.add(user)
    await db.commit()
    monkeypatch.setattr(cli, "AsyncSessionLocal", async_session_factory)

    created = await asyncio.to_thread(
        runner.invoke,
        cli.app,
        ["create-api-token", user.username, "--name", "CLI client", "--days", "7"],
    )

    assert created.exit_code == 0
    token_id = created.output.split("Token ID: ", 1)[1].splitlines()[0]
    raw_token = created.output.split("API Token (shown once): ", 1)[1].strip()
    assert raw_token.startswith(API_TOKEN_PREFIX)

    listed = await asyncio.to_thread(runner.invoke, cli.app, ["list-api-tokens", user.username])
    assert listed.exit_code == 0
    assert f"{token_id}\tactive" in listed.output
    assert raw_token not in listed.output

    revoked = await asyncio.to_thread(
        runner.invoke, cli.app, ["revoke-api-token", user.username, token_id]
    )
    assert revoked.exit_code == 0
    async with async_session_factory() as verification_db:
        assert await verify_api_token(verification_db, raw_token) is None


@pytest.mark.anyio
async def test_member_can_create_view_and_revoke_own_api_token_from_settings(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, user = await account_client(db, async_session_factory, tmp_path, monkeypatch)
    try:
        page = await client.get("/account/settings")
        assert page.status_code == 200
        assert "MCP 和 API Token" in page.text
        assert "http://testserver/api/v1/" in page.text
        assert "http://testserver/mcp/" in page.text
        assert "Authorization: Bearer YOUR_API_TOKEN" in page.text

        created = await client.post(
            "/account/api-tokens",
            data={"csrf_token": "test-csrf", "name": "Desktop MCP", "days": "30"},
        )
        token = await db.scalar(
            select(ApiToken).where(ApiToken.user_id == user.id, ApiToken.name == "Desktop MCP")
        )
        assert token is not None
        assert created.status_code == 201
        assert created.headers["cache-control"] == "no-store"
        assert API_TOKEN_PREFIX in created.text
        assert token.token_hash not in created.text

        revisited = await client.get("/account/settings")
        assert revisited.status_code == 200
        assert "Desktop MCP" in revisited.text
        assert API_TOKEN_PREFIX not in revisited.text

        revoked = await client.post(
            f"/account/api-tokens/{token.id}/revoke",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )
        await db.refresh(token)
        assert revoked.status_code == 303
        assert revoked.headers["location"] == "/account/settings#api-tokens"
        assert token.revoked_at is not None
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_member_cannot_revoke_another_users_api_token(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, _user = await account_client(db, async_session_factory, tmp_path, monkeypatch)
    try:
        other = User(username="other-token-owner", password_hash="unused")
        db.add(other)
        await db.commit()
        grant = await create_api_token(db, other, "Other token", expires_in_days=30)

        response = await client.post(
            f"/account/api-tokens/{grant.token_id}/revoke",
            data={"csrf_token": "test-csrf"},
        )

        assert response.status_code == 404
        assert await verify_api_token(db, grant.raw_token) is not None
    finally:
        await client.aclose()
