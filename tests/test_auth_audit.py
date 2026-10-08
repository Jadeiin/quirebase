import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from app_helpers import create_web_test_app, json_payload
from sqlalchemy import select

from quirebase.accounts import (
    InvalidCredentials,
    LoginThrottleConflict,
    authenticate_user,
    change_own_password,
    create_api_token,
    create_login_session,
)
from quirebase.audit import current_programmatic_invocation, programmatic_invocation
from quirebase.core import crypto
from quirebase.core.config import get_settings
from quirebase.core.crypto import hash_password, token_hash, verify_password
from quirebase.core.database import get_db
from quirebase.core.errors import ValidationFailure
from quirebase.models import AuditEvent, LoginSession, User


async def web_client(db, session_factory, *, authenticated: bool = False):
    test_app = create_web_test_app(mcp_session_factory=session_factory)

    async def override_db():
        await asyncio.sleep(0)
        yield db

    test_app.dependency_overrides[get_db] = override_db
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=test_app),
        base_url="http://testserver",
        headers={
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "http://testserver",
        },
    )
    user = None
    if authenticated:
        user = User(username="reader", password_hash="unused")
        db.add(user)
        await db.flush()
        _login, raw = await create_login_session(db, user, session_days=1)
        client.cookies.set(get_settings().session_cookie, raw)
    return client, user


@pytest.mark.anyio
async def test_failed_and_successful_logins_are_audited_without_credentials(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="audited", password_hash=hash_password("correct-password"))
    db.add(user)
    await db.commit()
    client, _ = await web_client(db, async_session_factory)
    try:
        failed = await client.post(
            "/api/v1/session",
            json=json_payload({"username": "audited", "password": "wrong-password"}),
        )
        assert failed.status_code == 401
        succeeded = await client.post(
            "/api/v1/session",
            json=json_payload({"username": "audited", "password": "correct-password"}),
        )
        assert succeeded.status_code == 200
        assert succeeded.json()["authenticated"] is True

        events = (
            await db.scalars(
                select(AuditEvent)
                .where(AuditEvent.action.in_(["auth.login.failed", "auth.login.succeeded"]))
                .order_by(AuditEvent.created_at)
            )
        ).all()
        assert [event.action for event in events] == [
            "auth.login.failed",
            "auth.login.succeeded",
        ]
        assert events[0].actor_id is None
        assert events[0].target_id == str(user.id)
        assert events[1].actor_id == user.id
        for event in events:
            assert event.source == "http"
            assert event.detail["invocation"] == {
                "protocol": "http",
                "operation": "login_session",
            }
        assert current_programmatic_invocation() is None
        assert await db.get(LoginSession, events[1].target_id) is not None
        details = " ".join(json.dumps(event.detail) for event in events)
        assert "correct-password" not in details
        assert "wrong-password" not in details
        assert "audited" not in details
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_login_counter_conflict_returns_409_without_login_side_effects(
    async_db, async_session_factory, monkeypatch
):
    db = async_db
    user = User(username="conflicting-login", password_hash=hash_password("correct-password"))
    db.add(user)
    await db.commit()

    async def conflicting_failure(_db, _identity):  # ruff: ignore[unused-async]
        raise LoginThrottleConflict("login failure counter changed concurrently; try again")

    monkeypatch.setattr(
        "quirebase.accounts.authentication.record_login_failure", conflicting_failure
    )
    client, _ = await web_client(db, async_session_factory)
    try:
        rejected = await client.post(
            "/api/v1/session",
            json=json_payload({"username": user.username, "password": "wrong-password"}),
        )
        assert rejected.status_code == 409
        assert rejected.json()["code"] == "login_throttle_conflict"
        assert "set-cookie" not in rejected.headers
        assert (await client.get("/api/v1/session")).json()["authenticated"] is False
        assert (
            await db.scalars(select(LoginSession).where(LoginSession.user_id == user.id))
        ).all() == []
        assert (
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action.in_([
                        "auth.login.failed",
                        "auth.login.succeeded",
                        "auth.login.throttled",
                    ])
                )
            )
        ).all() == []
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_http_audit_preserves_mcp_provenance_and_isolates_cookie_credentials(
    async_db, async_session_factory
):
    db = async_db
    client, user = await web_client(db, async_session_factory, authenticated=True)
    assert user is not None
    grant = await create_api_token(db, user, "Caller", expires_in_days=1)
    headers = {"Authorization": f"Bearer {grant.raw_token}"}
    try:
        bearer = await client.post(
            "/api/v1/account/api-tokens",
            json=json_payload({"name": "Bearer child", "days": 1}),
            headers=headers,
        )
        with programmatic_invocation("mcp", "account.create_own_api_token", client_id="test-mcp"):
            mcp = await client.post(
                "/api/v1/account/api-tokens",
                json=json_payload({"name": "MCP child", "days": 1}),
                headers=headers,
            )
        cookie = await client.post(
            "/api/v1/account/api-tokens", json=json_payload({"name": "Cookie child", "days": 1})
        )
        for response, protocol, operation, client_id in (
            (bearer, "http", "create_own_api_token", "http-api"),
            (mcp, "mcp", "account.create_own_api_token", "test-mcp"),
            (cookie, "http", "create_own_api_token", None),
        ):
            assert response.status_code == 201
            event = await db.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "auth.api_token.create",
                    AuditEvent.target_id == str(response.json()["id"]),
                )
            )
            assert event is not None
            assert event.source == protocol
            expected = {"protocol": protocol, "operation": operation}
            if client_id is not None:
                expected.update(api_token_id=grant.token_id, client_id=client_id)
            assert event.detail["invocation"] == json_payload(expected)
        assert current_programmatic_invocation() is None
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_password_verification_does_not_block_the_event_loop(async_db, monkeypatch):
    db = async_db
    password = "correct-password"
    user = User(username="threaded-password", password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    started = asyncio.Event()
    release_worker = threading.Event()
    loop = asyncio.get_running_loop()
    original_verify = crypto.HashedPassword.verify_and_update

    def delayed_verify(encoded, candidate):
        loop.call_soon_threadsafe(started.set)
        release_worker.wait()
        return original_verify(encoded, candidate)

    monkeypatch.setattr(crypto.HashedPassword, "verify_and_update", delayed_verify)
    authentication = asyncio.create_task(
        authenticate_user(db, "threaded-identity", user.username, password)
    )
    await asyncio.wait_for(started.wait(), 1)
    event_loop_advanced = asyncio.Event()
    loop.call_soon(event_loop_advanced.set)
    await asyncio.wait_for(event_loop_advanced.wait(), 1)
    release_worker.set()
    login, _raw = await authentication
    assert login.user_id == user.id


@pytest.mark.anyio
async def test_password_hashing_does_not_block_the_event_loop(monkeypatch):
    started = asyncio.Event()
    release_worker = threading.Event()
    loop = asyncio.get_running_loop()
    original_hash = crypto.hash_password

    def delayed_hash(password):
        loop.call_soon_threadsafe(started.set)
        release_worker.wait()
        return original_hash(password)

    monkeypatch.setattr(crypto, "hash_password", delayed_hash)
    hashing = asyncio.create_task(crypto.hash_password_async("threaded-password"))
    await asyncio.wait_for(started.wait(), 1)
    event_loop_advanced = asyncio.Event()
    loop.call_soon(event_loop_advanced.set)
    await asyncio.wait_for(event_loop_advanced.wait(), 1)
    release_worker.set()
    assert verify_password(await hashing, "threaded-password")


@pytest.mark.anyio
async def test_revoke_all_sessions_requires_same_origin_and_invalidates_every_session(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    db = async_db
    client, user = await web_client(db, async_session_factory, authenticated=True)
    assert user is not None
    db.add(
        LoginSession(
            token_hash=token_hash("another-session"),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db.commit()
    try:
        rejected = await client.delete(
            "/api/v1/account/sessions", headers={"Origin": "https://attacker.example"}
        )
        assert rejected.status_code == 403
        assert (
            await db.scalar(select(LoginSession).where(LoginSession.user_id == user.id).limit(1))
            is not None
        )

        response = await client.delete("/api/v1/account/sessions")
        assert response.status_code == 200
        assert get_settings().session_cookie in response.headers["set-cookie"]
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert (
            await db.scalars(select(LoginSession).where(LoginSession.user_id == user.id))
        ).all() == []

        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "auth.sessions.revoke_all")
        )
        assert event is not None
        assert event.actor_id == user.id
        assert event.detail["revoked_sessions"] == 2
        assert event.source == "http"
        assert event.detail["invocation"]["protocol"] == "http"
        assert (await client.get("/api/v1/session")).json()["authenticated"] is False
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_throttled_login_is_audited(async_db, async_session_factory):
    db = async_db
    client, _ = await web_client(db, async_session_factory)
    try:
        for _ in range(5):
            assert (
                await client.post(
                    "/api/v1/session",
                    json=json_payload({"username": "missing", "password": "not-a-password"}),
                )
            ).status_code == 401
        throttled = await client.post(
            "/api/v1/session",
            json=json_payload({"username": "missing", "password": "not-a-password"}),
        )
        assert throttled.status_code == 429
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "auth.login.throttled")
        )
        assert event is not None
        assert event.actor_id is None
        assert "missing" not in (event.detail or "")
        assert "not-a-password" not in (event.detail or "")
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_change_own_password_validates_current_password_and_audits(async_db):
    db = async_db
    user = User(username="changer", password_hash=hash_password("correct-password"))
    db.add(user)
    await db.commit()

    with pytest.raises(InvalidCredentials, match="Current password incorrect"):
        await change_own_password(db, user, "wrong-password", "new-secret-password-1")
    assert verify_password(user.password_hash, "correct-password")

    await change_own_password(db, user, "correct-password", "new-secret-password-1")
    assert verify_password(user.password_hash, "new-secret-password-1")

    event = await db.scalar(
        select(AuditEvent).where(AuditEvent.action == "account.password.changed")
    )
    assert event is not None
    assert event.actor_id == user.id
    assert event.target_id == str(user.id)


@pytest.mark.anyio
async def test_change_own_password_rejects_weak_new_password(async_db):
    db = async_db
    user = User(username="weak-changer", password_hash=hash_password("correct-password"))
    db.add(user)
    await db.commit()

    with pytest.raises(ValidationFailure):
        await change_own_password(db, user, "correct-password", "short")
    assert verify_password(user.password_hash, "correct-password")
    assert (
        await db.scalar(select(AuditEvent).where(AuditEvent.action == "account.password.changed"))
        is None
    )


@pytest.mark.anyio
async def test_account_settings_and_password_update(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    db = async_db
    client, user = await web_client(db, async_session_factory, authenticated=True)
    assert user is not None
    user.password_hash = hash_password("correct-password")
    await db.commit()

    page = await client.get("/api/v1/account")
    assert page.status_code == 200
    assert page.json()["user"]["username"] == "reader"

    # Wrong current password returns 422
    wrong = await client.put(
        "/api/v1/account/password",
        json=json_payload({
            "current_password": "wrong-current-password",
            "new_password": "new-secret-password-1",
        }),
    )
    assert wrong.status_code == 400
    assert "Current password incorrect" in wrong.text

    # Successful update
    success = await client.put(
        "/api/v1/account/password",
        json=json_payload({
            "current_password": "correct-password",
            "new_password": "new-secret-password-1",
        }),
    )
    assert success.status_code == 200
    assert success.json() == {"ok": True}

    event = await db.scalar(
        select(AuditEvent).where(AuditEvent.action == "account.password.changed")
    )
    assert event is not None
    assert event.actor_id == user.id
