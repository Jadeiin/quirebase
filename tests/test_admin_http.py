from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from sqlalchemy import select

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.database import get_db
from quirebase.models import LoginSession, Project, SystemSetting, User
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
        transport=httpx2.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
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
        transport=httpx2.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    )
    client.cookies.set(get_settings().session_cookie, raw)
    return client, user, login


@pytest.mark.anyio
async def test_admin_pages_accessible_by_admin(async_db, tmp_path, monkeypatch):
    client, _user, _ = await admin_client(async_db, tmp_path, monkeypatch)

    for path in [
        "/api/v1/admin/overview",
        "/api/v1/admin/users",
        "/api/v1/admin/projects",
        "/api/v1/admin/items",
        "/api/v1/admin/audit",
        "/api/v1/admin/workflows",
        "/api/v1/admin/settings",
        "/api/v1/admin/maintenance",
    ]:
        res = await client.get(path)
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("application/json")
    await client.aclose()


@pytest.mark.anyio
async def test_admin_project_directory_links_to_later_filtered_pages(
    async_db, tmp_path, monkeypatch
):
    client, admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    async_db.add_all([
        Project(name=f"Paged project {index:02d}", created_by=admin.id) for index in range(21)
    ])
    await async_db.commit()

    first = await client.get(
        "/api/v1/admin/projects",
        params={"search": "Paged", "state": "active", "visibility": "private"},
    )
    assert first.status_code == 200
    assert first.json()["page"] == 1
    assert first.json()["total"] == 21
    assert len(first.json()["projects"]) == 20

    second = await client.get(
        "/api/v1/admin/projects",
        params={
            "search": "Paged",
            "state": "active",
            "visibility": "private",
            "page": 2,
        },
    )
    assert second.status_code == 200
    assert second.json()["page"] == 2
    assert len(second.json()["projects"]) == 1
    await client.aclose()


@pytest.mark.anyio
async def test_admin_workflow_filter_rejects_unknown_state(async_db, tmp_path, monkeypatch):
    client, _user, _login = await admin_client(async_db, tmp_path, monkeypatch)
    try:
        response = await client.get("/api/v1/admin/workflows", params={"state": "unknown"})

        assert response.status_code == 422
        assert "unknown workflow state" in response.text
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_pages_forbidden_for_member(async_db, tmp_path, monkeypatch):
    client, _user, _ = await member_client(async_db, tmp_path, monkeypatch)

    for path in [
        "/api/v1/admin/overview",
        "/api/v1/admin/users",
        "/api/v1/admin/items",
        "/api/v1/admin/audit",
        "/api/v1/admin/workflows",
        "/api/v1/admin/settings",
        "/api/v1/admin/maintenance",
    ]:
        res = await client.get(path)
        assert res.status_code in (403, 404, 500)
    await client.aclose()


@pytest.mark.anyio
async def test_admin_create_user_endpoint(async_db, tmp_path, monkeypatch):
    db = async_db
    client, _admin, _login = await admin_client(db, tmp_path, monkeypatch)

    res = await client.post(
        "/api/v1/admin/users",
        json={
            "username": "http_created_user",
            "password": "strong_password_123",
            "role": "member",
        },
    )
    assert res.status_code == 201
    assert res.json()["username"] == "http_created_user"

    created = await db.scalar(select(User).where(User.username == "http_created_user"))
    assert created is not None
    assert created.role == "member"
    await client.aclose()


@pytest.mark.anyio
async def test_admin_settings_endpoint(async_db, tmp_path, monkeypatch):
    db = async_db
    client, _admin, _login = await admin_client(db, tmp_path, monkeypatch)

    res = await client.put(
        "/api/v1/admin/settings",
        json={
            "metadata_contact_email": "http_admin@institution.edu",
            "ncbi_api_key": "ncbi_key_xyz",
            "openalex_api_key": "",
            "nasa_ads_token": "",
            "ieee_api_key": "",
            "session_days": 60,
            "max_pdf_bytes": 104857600,
            "max_attachment_bytes": 104857600,
            "export_ttl_hours": 48,
        },
    )
    assert res.status_code == 200

    setting = await db.get(SystemSetting, "metadata_contact_email")
    assert setting is not None
    assert setting.value == "http_admin@institution.edu"
    await client.aclose()


@pytest.mark.anyio
async def test_admin_maintenance_triggers(async_db, tmp_path, monkeypatch, fake_durable_operations):
    db = async_db
    client, _admin, _login = await admin_client(db, tmp_path, monkeypatch)

    routes = {
        "/api/v1/admin/maintenance/reindex_all": "reindex_all",
        "/api/v1/admin/maintenance/check_objects": "check_objects",
        "/api/v1/admin/maintenance/backup": "backup",
        "/api/v1/admin/maintenance/recommend_tags_all": "recommend_tags_all",
    }
    for route, operation in routes.items():
        res = await client.post(
            route,
            json={},
        )
        assert res.status_code == 200
        workflow_id = res.json()["id"]
        assert workflow_id.startswith(f"maintenance:{operation}:")
        progress = await client.get(f"/api/v1/admin/workflows/{workflow_id}")
        assert progress.status_code == 200
        assert progress.json()["id"] == workflow_id

    assert {row.name for row in await fake_durable_operations.list()} == {
        "operations.reindex_all",
        "operations.check_objects",
        "operations.backup",
        "operations.recommend_tags_all",
    }
    await client.aclose()
