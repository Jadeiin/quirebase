from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_http import authenticated_client

from quirebase.accounts import InvalidCredentials, change_own_password
from quirebase.core.config import get_settings
from quirebase.core.crypto import hash_password, token_hash, verify_password
from quirebase.core.database import get_db
from quirebase.core.errors import ValidationFailure
from quirebase.models import AuditEvent, LoginSession, User
from quirebase.web.app import app


def test_failed_and_successful_logins_are_audited_without_credentials(db):
    user = User(username="audited", password_hash=hash_password("correct-password"))
    db.add(user)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        failed = client.post("/login", data={"username": "audited", "password": "wrong-password"})
        assert failed.status_code == 401
        succeeded = client.post(
            "/login",
            data={"username": "audited", "password": "correct-password"},
            follow_redirects=False,
        )
        assert succeeded.status_code == 303

        events = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.action.in_(["auth.login.failed", "auth.login.succeeded"]))
            .order_by(AuditEvent.created_at)
        ).all()
        assert [event.action for event in events] == [
            "auth.login.failed",
            "auth.login.succeeded",
        ]
        assert events[0].actor_id is None
        assert events[0].target_id == user.id
        assert events[1].actor_id == user.id
        assert db.get(LoginSession, events[1].target_id) is not None
        details = " ".join(event.detail or "" for event in events)
        assert "correct-password" not in details
        assert "wrong-password" not in details
        assert "audited" not in details
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_revoke_all_sessions_requires_csrf_and_invalidates_every_session(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    user = db.scalar(select(User).where(User.username == "reader"))
    db.add(
        LoginSession(
            token_hash=token_hash("another-session"),
            csrf_token="another-csrf",
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    db.commit()
    try:
        rejected = client.post("/account/sessions/revoke-all", follow_redirects=False)
        assert rejected.status_code == 403
        assert (
            db.scalar(select(LoginSession).where(LoginSession.user_id == user.id).limit(1))
            is not None
        )

        response = client.post(
            "/account/sessions/revoke-all?csrf_token=test-csrf", follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
        assert get_settings().session_cookie in response.headers["set-cookie"]
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert db.scalars(select(LoginSession).where(LoginSession.user_id == user.id)).all() == []

        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.sessions.revoke_all"))
        assert event.actor_id == user.id
        assert '"revoked_sessions": 2' in event.detail
        assert client.get("/").status_code == 401
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_throttled_login_is_audited(db):
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        for _ in range(5):
            assert (
                client.post(
                    "/login", data={"username": "missing", "password": "not-a-password"}
                ).status_code
                == 401
            )
        throttled = client.post(
            "/login", data={"username": "missing", "password": "not-a-password"}
        )
        assert throttled.status_code == 429
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.login.throttled"))
        assert event is not None
        assert event.actor_id is None
        assert "missing" not in (event.detail or "")
        assert "not-a-password" not in (event.detail or "")
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_change_own_password_validates_current_password_and_audits(db):
    user = User(username="changer", password_hash=hash_password("correct-password"))
    db.add(user)
    db.commit()

    with pytest.raises(InvalidCredentials, match="Current password incorrect"):
        change_own_password(db, user, "wrong-password", "new-secret-password-1")
    assert verify_password(user.password_hash, "correct-password")

    change_own_password(db, user, "correct-password", "new-secret-password-1")
    assert verify_password(user.password_hash, "new-secret-password-1")

    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "account.password.changed"))
    assert event is not None
    assert event.actor_id == user.id
    assert event.target_id == user.id


def test_change_own_password_rejects_weak_new_password(db):
    user = User(username="weak-changer", password_hash=hash_password("correct-password"))
    db.add(user)
    db.commit()

    with pytest.raises(ValidationFailure):
        change_own_password(db, user, "correct-password", "short")
    assert verify_password(user.password_hash, "correct-password")
    assert (
        db.scalar(select(AuditEvent).where(AuditEvent.action == "account.password.changed")) is None
    )


def test_account_settings_and_password_update(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    user = db.scalar(select(User).where(User.username == "reader"))
    assert user is not None
    user.password_hash = hash_password("correct-password")
    db.commit()

    page = client.get("/account/settings")
    assert page.status_code == 200
    assert "reader" in page.text
    assert "quirebase:export-preferences:v1" in page.text

    # Password mismatch returns 422
    mismatch = client.post(
        "/account/settings/password?csrf_token=test-csrf",
        data={
            "current_password": "correct-password",
            "new_password": "new-secret-password-1",
            "confirm_password": "different-password",
        },
    )
    assert mismatch.status_code == 422
    assert "New passwords do not match" in mismatch.text

    # Wrong current password returns 422
    wrong = client.post(
        "/account/settings/password?csrf_token=test-csrf",
        data={
            "current_password": "wrong-current-password",
            "new_password": "new-secret-password-1",
            "confirm_password": "new-secret-password-1",
        },
    )
    assert wrong.status_code == 422
    assert "Current password incorrect" in wrong.text

    # Successful update
    success = client.post(
        "/account/settings/password?csrf_token=test-csrf",
        data={
            "current_password": "correct-password",
            "new_password": "new-secret-password-1",
            "confirm_password": "new-secret-password-1",
        },
    )
    assert success.status_code == 200
    assert "Password updated successfully" in success.text

    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "account.password.changed"))
    assert event is not None
    assert event.actor_id == user.id

    # Switch locale to zh_CN
    loc_resp = client.post(
        "/account/settings/locale?csrf_token=test-csrf",
        data={"locale": "zh_CN"},
        follow_redirects=False,
    )
    assert loc_resp.status_code == 303
    assert loc_resp.headers["location"] == "/account/settings"
    assert "quirebase_locale=zh_CN" in loc_resp.headers.get("set-cookie", "")
