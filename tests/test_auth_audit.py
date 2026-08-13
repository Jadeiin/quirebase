from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_http import authenticated_client

from quirebase.app import app
from quirebase.config import get_settings
from quirebase.db import get_db
from quirebase.models import AuditEvent, LoginSession, User
from quirebase.security import hash_password, token_hash


def test_failed_and_successful_logins_are_audited_without_credentials(db):
    user = User(username="audited", password_hash=hash_password("correct-password"))
    db.add(user)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        failed = client.post(
            "/login", data={"username": "audited", "password": "wrong-password"}
        )
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


def test_revoke_all_sessions_requires_csrf_and_invalidates_every_session(
    db, tmp_path, monkeypatch
):
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
        assert db.scalar(
            select(LoginSession).where(LoginSession.user_id == user.id).limit(1)
        ) is not None

        response = client.post(
            "/account/sessions/revoke-all?csrf_token=test-csrf", follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
        assert get_settings().session_cookie in response.headers["set-cookie"]
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert db.scalars(
            select(LoginSession).where(LoginSession.user_id == user.id)
        ).all() == []

        event = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "auth.sessions.revoke_all")
        )
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
            assert client.post(
                "/login", data={"username": "missing", "password": "not-a-password"}
            ).status_code == 401
        throttled = client.post(
            "/login", data={"username": "missing", "password": "not-a-password"}
        )
        assert throttled.status_code == 429
        event = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "auth.login.throttled")
        )
        assert event is not None
        assert event.actor_id is None
        assert "missing" not in (event.detail or "")
        assert "not-a-password" not in (event.detail or "")
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
