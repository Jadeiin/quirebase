import asyncio
import threading
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlalchemy import select

from quirebase.accounts import (
    InvalidCredentials,
    authenticate_user,
    change_own_password,
    create_login_session,
)
from quirebase.core import crypto
from quirebase.core.config import get_settings
from quirebase.core.crypto import hash_password, token_hash, verify_password
from quirebase.core.database import get_db
from quirebase.core.errors import ValidationFailure
from quirebase.models import AuditEvent, LoginSession, User
from quirebase.web.app import create_app


async def web_client(db, session_factory, *, authenticated: bool = False):
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
    user = None
    if authenticated:
        user = User(username="reader", password_hash="unused")
        db.add(user)
        await db.flush()
        login, raw = await create_login_session(db, user, session_days=1)
        login.csrf_token = "test-csrf"
        await db.commit()
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
            "/login", data={"username": "audited", "password": "wrong-password"}
        )
        assert failed.status_code == 401
        succeeded = await client.post(
            "/login",
            data={"username": "audited", "password": "correct-password"},
            follow_redirects=False,
        )
        assert succeeded.status_code == 303

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
        assert events[0].target_id == user.id
        assert events[1].actor_id == user.id
        assert await db.get(LoginSession, events[1].target_id) is not None
        details = " ".join(event.detail or "" for event in events)
        assert "correct-password" not in details
        assert "wrong-password" not in details
        assert "audited" not in details
    finally:
        await client.aclose()
        get_settings.cache_clear()


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
    original_verify = crypto.verify_password

    def delayed_verify(encoded, candidate):
        loop.call_soon_threadsafe(started.set)
        release_worker.wait()
        return original_verify(encoded, candidate)

    monkeypatch.setattr(crypto, "verify_password", delayed_verify)
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
async def test_revoke_all_sessions_requires_csrf_and_invalidates_every_session(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    db = async_db
    client, user = await web_client(db, async_session_factory, authenticated=True)
    assert user is not None
    db.add(
        LoginSession(
            token_hash=token_hash("another-session"),
            csrf_token="another-csrf",
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db.commit()
    try:
        rejected = await client.post("/account/sessions/revoke-all", follow_redirects=False)
        assert rejected.status_code == 403
        assert (
            await db.scalar(select(LoginSession).where(LoginSession.user_id == user.id).limit(1))
            is not None
        )

        response = await client.post(
            "/account/sessions/revoke-all", follow_redirects=False, data={"csrf_token": "test-csrf"}
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
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
        assert '"revoked_sessions": 2' in event.detail
        assert (await client.get("/")).status_code == 401
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
                    "/login", data={"username": "missing", "password": "not-a-password"}
                )
            ).status_code == 401
        throttled = await client.post(
            "/login", data={"username": "missing", "password": "not-a-password"}
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
    assert event.target_id == user.id


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

    page = await client.get("/account/settings")
    assert page.status_code == 200
    assert "reader" in page.text
    assert "quirebase:export-preferences:v1" in page.text

    # Password mismatch returns 422
    mismatch = await client.post(
        "/account/settings/password",
        data={
            "csrf_token": "test-csrf",
            "current_password": "correct-password",
            "new_password": "new-secret-password-1",
            "confirm_password": "different-password",
        },
    )
    assert mismatch.status_code == 422
    assert "两次输入的新密码不一致" in mismatch.text

    # Wrong current password returns 422
    wrong = await client.post(
        "/account/settings/password",
        data={
            "csrf_token": "test-csrf",
            "current_password": "wrong-current-password",
            "new_password": "new-secret-password-1",
            "confirm_password": "new-secret-password-1",
        },
    )
    assert wrong.status_code == 422
    assert "当前密码不正确" in wrong.text

    # Successful update
    success = await client.post(
        "/account/settings/password",
        data={
            "csrf_token": "test-csrf",
            "current_password": "correct-password",
            "new_password": "new-secret-password-1",
            "confirm_password": "new-secret-password-1",
        },
    )
    assert success.status_code == 200
    assert "密码更新成功" in success.text

    event = await db.scalar(
        select(AuditEvent).where(AuditEvent.action == "account.password.changed")
    )
    assert event is not None
    assert event.actor_id == user.id

    # Switch locale to zh_CN
    loc_resp = await client.post(
        "/account/settings/locale",
        data={"csrf_token": "test-csrf", "locale": "zh_CN"},
        follow_redirects=False,
    )
    assert loc_resp.status_code == 303
    assert loc_resp.headers["location"] == "/account/settings"
    assert "quirebase_locale=zh_CN" in loc_resp.headers.get("set-cookie", "")
