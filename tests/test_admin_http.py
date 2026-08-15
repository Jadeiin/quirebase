from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.database import get_db
from quirebase.models import Job, LoginSession, SystemSetting, User
from quirebase.web.app import app


def admin_client(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    user = User(
        username="admin_runner",
        password_hash="unused",
        role="administrator",
        active=True,
    )
    db.add(user)
    db.flush()
    raw = "admin-session-raw-token"
    login = LoginSession(
        token_hash=token_hash(raw),
        csrf_token="test-admin-csrf",
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(login)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.cookies.set(get_settings().session_cookie, raw)
    return client, user, login


def member_client(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    user = User(
        username="member_runner",
        password_hash="unused",
        role="member",
        active=True,
    )
    db.add(user)
    db.flush()
    raw = "member-session-raw-token"
    login = LoginSession(
        token_hash=token_hash(raw),
        csrf_token="test-member-csrf",
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(login)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.cookies.set(get_settings().session_cookie, raw)
    return client, user, login


def test_admin_pages_accessible_by_admin(db, tmp_path, monkeypatch):
    client, _user, _ = admin_client(db, tmp_path, monkeypatch)

    for path in [
        "/admin",
        "/admin/users",
        "/admin/items",
        "/admin/audit",
        "/admin/jobs",
        "/admin/settings",
        "/admin/maintenance",
    ]:
        res = client.get(path)
        assert res.status_code == 200
        assert "Administration" in res.text or "Quirebase" in res.text


def test_admin_pages_forbidden_for_member(db, tmp_path, monkeypatch):
    client, _user, _ = member_client(db, tmp_path, monkeypatch)

    for path in [
        "/admin",
        "/admin/users",
        "/admin/items",
        "/admin/audit",
        "/admin/jobs",
        "/admin/settings",
        "/admin/maintenance",
    ]:
        res = client.get(path)
        assert res.status_code in (403, 404, 500)


def test_admin_create_user_endpoint(db, tmp_path, monkeypatch):
    client, _admin, login = admin_client(db, tmp_path, monkeypatch)

    res = client.post(
        f"/admin/users/create?csrf_token={login.csrf_token}",
        data={
            "username": "http_created_user",
            "password": "strong_password_123",
            "role": "member",
        },
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/admin/users"

    created = db.scalar(select(User).where(User.username == "http_created_user"))
    assert created is not None
    assert created.role == "member"


def test_admin_settings_endpoint(db, tmp_path, monkeypatch):
    client, _admin, login = admin_client(db, tmp_path, monkeypatch)

    res = client.post(
        f"/admin/settings?csrf_token={login.csrf_token}",
        data={
            "metadata_contact_email": "http_admin@institution.edu",
            "ncbi_api_key": "ncbi_key_xyz",
            "openalex_api_key": "",
            "nasa_ads_token": "",
            "ieee_api_key": "",
            "session_days": "60",
            "max_pdf_bytes": "104857600",
            "max_attachment_bytes": "104857600",
            "export_ttl_hours": "48",
        },
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/admin/settings"

    setting = db.get(SystemSetting, "metadata_contact_email")
    assert setting is not None
    assert setting.value == "http_admin@institution.edu"


def test_admin_maintenance_triggers(db, tmp_path, monkeypatch):
    client, _admin, login = admin_client(db, tmp_path, monkeypatch)

    # Reindex trigger
    res = client.post(
        f"/admin/maintenance/reindex?csrf_token={login.csrf_token}",
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/admin/jobs"

    reindex_job = db.scalar(select(Job).where(Job.kind == "system.reindex_all"))
    assert reindex_job is not None

    # Check objects trigger
    res = client.post(
        f"/admin/maintenance/check-objects?csrf_token={login.csrf_token}",
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/admin/jobs"

    check_job = db.scalar(select(Job).where(Job.kind == "system.check_objects"))
    assert check_job is not None
