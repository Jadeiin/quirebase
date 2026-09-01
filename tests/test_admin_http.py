from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlalchemy import select

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.database import get_db
from quirebase.models import Job, LoginSession, SystemSetting, User
from quirebase.web.app import app


async def admin_client(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    user = User(
        username="admin_runner",
        password_hash="unused",
        role="administrator",
        active=True,
    )
    db.add(user)
    await db.flush()
    raw = "admin-session-raw-token"
    login = LoginSession(
        token_hash=token_hash(raw),
        csrf_token="test-admin-csrf",
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(login)
    await db.commit()

    async def override_db():
        await asyncio.sleep(0)
        yield db

    app.dependency_overrides[get_db] = override_db
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
    )
    client.cookies.set(get_settings().session_cookie, raw)
    return client, user, login


async def member_client(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    user = User(
        username="member_runner",
        password_hash="unused",
        role="member",
        active=True,
    )
    db.add(user)
    await db.flush()
    raw = "member-session-raw-token"
    login = LoginSession(
        token_hash=token_hash(raw),
        csrf_token="test-member-csrf",
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(login)
    await db.commit()

    async def override_db():
        await asyncio.sleep(0)
        yield db

    app.dependency_overrides[get_db] = override_db
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
    )
    client.cookies.set(get_settings().session_cookie, raw)
    return client, user, login


@pytest.mark.anyio
async def test_admin_pages_accessible_by_admin(async_db, tmp_path, monkeypatch):
    client, _user, _ = await admin_client(async_db, tmp_path, monkeypatch)

    for path in [
        "/admin",
        "/admin/users",
        "/admin/items",
        "/admin/audit",
        "/admin/jobs",
        "/admin/settings",
        "/admin/maintenance",
    ]:
        res = await client.get(path)
        assert res.status_code == 200
        assert "Administration" in res.text or "Quirebase" in res.text
    await client.aclose()


@pytest.mark.anyio
async def test_admin_pages_forbidden_for_member(async_db, tmp_path, monkeypatch):
    client, _user, _ = await member_client(async_db, tmp_path, monkeypatch)

    for path in [
        "/admin",
        "/admin/users",
        "/admin/items",
        "/admin/audit",
        "/admin/jobs",
        "/admin/settings",
        "/admin/maintenance",
    ]:
        res = await client.get(path)
        assert res.status_code in (403, 404, 500)
    await client.aclose()


@pytest.mark.anyio
async def test_admin_create_user_endpoint(async_db, tmp_path, monkeypatch):
    db = async_db
    client, _admin, login = await admin_client(db, tmp_path, monkeypatch)

    res = await client.post(
        "/admin/users/create",
        data={
            "csrf_token": login.csrf_token,
            "username": "http_created_user",
            "password": "strong_password_123",
            "role": "member",
        },
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/admin/users"

    created = await db.scalar(select(User).where(User.username == "http_created_user"))
    assert created is not None
    assert created.role == "member"
    await client.aclose()


@pytest.mark.anyio
async def test_admin_settings_endpoint(async_db, tmp_path, monkeypatch):
    db = async_db
    client, _admin, login = await admin_client(db, tmp_path, monkeypatch)

    res = await client.post(
        "/admin/settings",
        data={
            "csrf_token": login.csrf_token,
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

    setting = await db.get(SystemSetting, "metadata_contact_email")
    assert setting is not None
    assert setting.value == "http_admin@institution.edu"
    await client.aclose()


@pytest.mark.anyio
async def test_admin_maintenance_triggers(async_db, tmp_path, monkeypatch):
    db = async_db
    client, _admin, login = await admin_client(db, tmp_path, monkeypatch)

    # Reindex trigger
    res = await client.post(
        "/admin/maintenance/reindex",
        data={"csrf_token": login.csrf_token},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/admin/jobs"

    reindex_job = await db.scalar(select(Job).where(Job.kind == "system.reindex_all"))
    assert reindex_job is not None

    # Check objects trigger
    res = await client.post(
        "/admin/maintenance/check-objects",
        data={"csrf_token": login.csrf_token},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/admin/jobs"

    check_job = await db.scalar(select(Job).where(Job.kind == "system.check_objects"))
    assert check_job is not None

    # Backup trigger
    res = await client.post(
        "/admin/maintenance/backup",
        data={"csrf_token": login.csrf_token},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/admin/jobs"

    backup_job = await db.scalar(select(Job).where(Job.kind == "system.backup"))
    assert backup_job is not None

    # Complete the job and verify download
    from quirebase.pipeline import run_job

    await run_job(db, backup_job)
    assert backup_job.state == "succeeded"

    download_res = await client.get(f"/admin/maintenance/backups/{backup_job.id}/download")
    assert download_res.status_code == 200
    assert download_res.headers["content-type"] == "application/zip"
    await client.aclose()
