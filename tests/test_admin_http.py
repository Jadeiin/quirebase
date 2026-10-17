from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx2
import pytest
from app_helpers import json_payload
from sqlalchemy import select
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.access import SystemAction
from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.database import get_db
from quirebase.core.workflows import WorkflowSummary
from quirebase.models import AuditEvent, Invitation, LoginSession, SystemSetting, User
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
    await provision_initial_workspace(db, user)
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
async def test_admin_invitation_lifecycle_and_paginated_history(async_db, tmp_path, monkeypatch):
    client, _admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    try:
        created = await client.post("/api/v1/admin/invitations", json={"username": "http-invitee"})
        assert created.status_code == 201
        original = created.json()
        reissued = await client.post(f"/api/v1/admin/invitations/{original['id']}/reissue")
        assert reissued.status_code == 201
        replacement = reissued.json()
        assert replacement["id"] != original["id"]
        assert replacement["token"] != original["token"]
        assert (await client.get(f"/api/v1/invitations/{original['token']}")).status_code == 404
        assert (await client.get(f"/api/v1/invitations/{replacement['token']}")).status_code == 200

        page = (await client.get("/api/v1/admin/invitations?limit=1&offset=1")).json()
        assert page["total"] == 2 and page["limit"] == 1 and page["offset"] == 1
        assert page["items"][0]["id"] == original["id"]
        assert page["items"][0]["state"] == "revoked"
        assert page["items"][0]["revoked_at"] is not None
        assert not {"token", "token_hash", "accept_path"} & page["items"][0].keys()
        pending = (await client.get("/api/v1/admin/invitations?state=pending")).json()
        assert pending["total"] == 1
        assert pending["items"][0]["id"] == replacement["id"]
        assert (await client.get("/api/v1/admin/overview")).json()["pending_invitation_count"] == 1

        for _ in range(2):
            revoked = await client.delete(f"/api/v1/admin/invitations/{replacement['id']}")
            assert revoked.status_code == 200
        assert (await client.get(f"/api/v1/invitations/{replacement['token']}")).status_code == 404
        rejected = await client.post(
            f"/api/v1/invitations/{replacement['token']}/accept",
            json={"password": "password-123456"},
        )
        assert rejected.status_code == 404
        assert (await client.get("/api/v1/admin/overview")).json()["pending_invitation_count"] == 0
        assert (await client.get("/api/v1/admin/invitations?state=unknown")).status_code == 422
        assert (await client.get("/api/v1/admin/invitations?limit=101")).status_code == 422
        assert "invitations" not in (await client.get("/api/v1/admin/users")).json()
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_invitation_overview_excludes_expired_links(async_db, tmp_path, monkeypatch):
    client, admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    async_db.add(
        Invitation(
            token_hash=token_hash("expired-link"),
            username="expired-http-invitee",
            role="member",
            created_by=admin.id,
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await async_db.commit()
    try:
        assert (await client.get("/api/v1/admin/overview")).json()["pending_invitation_count"] == 0
        page = (await client.get("/api/v1/admin/invitations?state=expired")).json()
        assert page["total"] == 1 and page["items"][0]["state"] == "expired"
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/admin/invitations"),
        ("DELETE", "/api/v1/admin/invitations/00000000-0000-0000-0000-000000000001"),
        ("POST", "/api/v1/admin/invitations/00000000-0000-0000-0000-000000000001/reissue"),
    ],
)
async def test_invitation_administration_is_hidden_from_members(
    async_db, tmp_path, monkeypatch, method, path
):
    client, _member, _login = await member_client(async_db, tmp_path, monkeypatch)
    try:
        assert (await client.request(method, path)).status_code == 404
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_workspace_governance_directory(async_db, tmp_path, monkeypatch):
    client, admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    response = await client.get("/api/v1/admin/workspaces")
    assert response.status_code == 200
    assert any(row["id"] == str(fixture_workspace_id(admin)) for row in response.json())
    await client.aclose()


@pytest.mark.anyio
async def test_administrator_can_disable_owner_then_explicitly_reassign_workspace(
    async_db, tmp_path, monkeypatch
):
    from quirebase.models import WorkspaceMember

    client, admin, _ = await admin_client(async_db, tmp_path, monkeypatch)
    admin_id = admin.id
    try:
        created = await client.post(
            "/api/v1/admin/users",
            json={
                "username": "offboarding-owner",
                "password": "password-123456",
            },
        )
        owner_id = created.json()["id"]
        disabled = await client.put(
            f"/api/v1/admin/users/{owner_id}/status", json={"active": False}
        )
        assert disabled.status_code == 200 and disabled.json()["active"] is False
        directory = (await client.get("/api/v1/admin/workspaces")).json()
        workspace = next(row for row in directory if row["owner_id"] == owner_id)
        assert workspace["owner_username"] == "offboarding-owner"
        assert workspace["owner_active"] is False and workspace["can_reassign_owner"] is True
        path = f"/api/v1/admin/workspaces/{workspace['id']}/owner"
        payload = {
            "new_owner_user_id": str(admin_id),
            "expected_owner_user_id": owner_id,
            "reason": "Explicit handover after offboarding",
        }
        updated = await client.post(path, json=payload)
        assert updated.status_code == 200
        assert updated.json()["owner_id"] == str(admin_id)
        assert updated.json()["owner_active"] is True
        assert (await client.post(path, json=payload)).status_code == 409
        await async_db.rollback()
        assert (
            await async_db.scalar(
                select(WorkspaceMember.id).where(
                    WorkspaceMember.workspace_id == workspace["id"],
                    WorkspaceMember.user_id == admin_id,
                )
            )
            is not None
        )
        assert (await client.post(path, json={**payload, "reason": "short"})).status_code == 422
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_workspace_reassignment_is_hidden_from_non_administrators(
    async_db, tmp_path, monkeypatch
):
    from uuid import uuid4

    client, _member, _login = await member_client(async_db, tmp_path, monkeypatch)
    try:
        response = await client.post(
            f"/api/v1/admin/workspaces/{uuid4()}/owner",
            json={
                "new_owner_user_id": str(uuid4()),
                "expected_owner_user_id": str(uuid4()),
                "reason": "Attempt a forbidden reassignment",
            },
        )
        assert response.status_code == 404
    finally:
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
async def test_admin_overview_pages_events_without_changing_statistics(
    async_db, tmp_path, monkeypatch, fake_durable_operations
):
    client, admin, _login = await admin_client(async_db, tmp_path, monkeypatch)

    monkeypatch.setattr(
        fake_durable_operations,
        "state_counts",
        AsyncMock(return_value={"failed": 123, "succeeded": 7}),
    )
    now = datetime.now(UTC)
    async_db.add_all([
        AuditEvent(
            actor_id=admin.id,
            action=f"test.event.{index}",
            target_type="instance",
            created_at=now + timedelta(seconds=index),
        )
        for index in range(27)
    ])
    await async_db.commit()
    try:
        first = await client.get("/api/v1/admin/overview", params={"limit": 10})
        assert first.status_code == 200
        first_page = first.json()
        assert first_page["failed_workflow_count"] == 123
        assert len(first_page["recent_events"]["items"]) == 10
        assert first_page["recent_events"]["total"] >= 27

        second = await client.get("/api/v1/admin/overview", params={"limit": 10, "offset": 10})
        assert second.status_code == 200
        second_page = second.json()
        assert second_page["recent_events"]["total"] == first_page["recent_events"]["total"]
        assert second_page["recent_events"]["offset"] == 10
        assert second_page["recent_events"]["limit"] == 10
        assert [row["action"] for row in second_page["recent_events"]["items"]] == [
            f"test.event.{index}" for index in range(16, 6, -1)
        ]
        for key in ("user_count", "pending_invitation_count", "failed_workflow_count", "storage"):
            assert second_page[key] == first_page[key]

        empty = await client.get("/api/v1/admin/overview", params={"limit": 10, "offset": 1000})
        assert empty.status_code == 200
        assert empty.json()["recent_events"]["items"] == []
        assert empty.json()["recent_events"]["total"] == first_page["recent_events"]["total"]
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_workflows_pages_complete_history_and_counts_filtered_states(
    async_db, tmp_path, monkeypatch, fake_durable_operations
):
    client, _admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    now = datetime.now(UTC)
    for index in range(150):
        state, raw_status = ("failed", "ERROR") if index % 3 == 0 else ("pending", "ENQUEUED")
        row = WorkflowSummary(
            id=f"workflow-{index}",
            name="operations.check_objects",
            state=state,
            raw_status=raw_status,
            queue_name="operations",
            executor_id=None,
            created_at=now + timedelta(seconds=index),
            updated_at=now + timedelta(seconds=index),
        )
        fake_durable_operations.workflows[row.id] = row
    try:
        response = await client.get("/api/v1/admin/workflows", params={"limit": 10, "offset": 100})
        assert response.status_code == 200
        page = response.json()
        assert (page["total"], page["limit"], page["offset"]) == (150, 10, 100)
        assert [row["id"] for row in page["items"]] == [
            f"workflow-{index}" for index in range(49, 39, -1)
        ]

        filtered = await client.get(
            "/api/v1/admin/workflows", params={"state": " FaIlEd ", "limit": 10, "offset": 10}
        )
        assert filtered.status_code == 200
        page = filtered.json()
        assert (page["total"], page["limit"], page["offset"]) == (50, 10, 10)
        assert [row["id"] for row in page["items"]] == [
            f"workflow-{index}" for index in range(117, 87, -3)
        ]
        assert all(row["state"] == "failed" for row in page["items"])

        empty = await client.get("/api/v1/admin/workflows", params={"state": "running"})
        assert empty.status_code == 200
        assert empty.json()["total"] == 0
        assert empty.json()["items"] == []

        past_end = await client.get("/api/v1/admin/workflows", params={"offset": 200})
        assert past_end.status_code == 200
        assert past_end.json()["total"] == 150
        assert past_end.json()["items"] == []
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("section", ["overview", "workflows"])
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
async def test_admin_pagination_rejects_invalid_bounds(
    async_db, tmp_path, monkeypatch, section, params
):
    client, _admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    try:
        response = await client.get(f"/api/v1/admin/{section}", params=params)
        assert response.status_code == 422
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_pages_forbidden_for_member(async_db, tmp_path, monkeypatch):
    client, _user, _ = await member_client(async_db, tmp_path, monkeypatch)

    for path in [
        "/api/v1/admin/overview",
        "/api/v1/admin/users",
        "/api/v1/admin/audit",
        "/api/v1/admin/workflows",
        "/api/v1/admin/settings",
        "/api/v1/admin/maintenance",
    ]:
        res = await client.get(path)
        assert res.status_code in {403, 404}, path
    await client.aclose()


@pytest.mark.anyio
async def test_admin_endpoint_relies_only_on_its_concrete_action(async_db, tmp_path, monkeypatch):
    client, _user, _login = await member_client(async_db, tmp_path, monkeypatch)

    def allow_audit_only(_role, action, *, relation="any"):
        return action is SystemAction.audit_read and relation == "any"

    monkeypatch.setattr(
        "quirebase.access.authorization.system_action_allowed",
        allow_audit_only,
    )
    try:
        response = await client.get("/api/v1/admin/audit")
        assert response.status_code == 200
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_create_user_endpoint(async_db, tmp_path, monkeypatch):
    db = async_db
    client, _admin, _login = await admin_client(db, tmp_path, monkeypatch)

    res = await client.post(
        "/api/v1/admin/users",
        json=json_payload({
            "username": "http_created_user",
            "password": "strong_password_123",
            "role": "member",
        }),
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
        json=json_payload({
            "metadata_contact_email": "http_admin@institution.edu",
            "ncbi_api_key": "ncbi_key_xyz",
            "openalex_api_key": "",
            "nasa_ads_token": "",
            "ieee_api_key": "",
            "session_days": 60,
            "max_pdf_bytes": 104857600,
            "max_attachment_bytes": 104857600,
            "export_ttl_hours": 48,
        }),
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

    routes = {"/api/v1/admin/maintenance/check_objects": "check_objects"}
    for route, operation in routes.items():
        res = await client.post(
            route,
            json=json_payload({}),
        )
        assert res.status_code == 200
        workflow_id = res.json()["id"]
        assert workflow_id.startswith(f"maintenance:{operation}:")
        progress = await client.get(f"/api/v1/admin/workflows/{workflow_id}")
        assert progress.status_code == 200
        assert progress.json()["id"] == workflow_id

    assert {row.name for row in await fake_durable_operations.list()} == {
        "operations.check_objects",
    }
    await client.aclose()
