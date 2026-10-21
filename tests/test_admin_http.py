from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

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
from quirebase.models import (
    AuditEvent,
    Invitation,
    LoginSession,
    MaintenanceSnapshot,
    SystemSetting,
    User,
    Workspace,
    WorkspaceMember,
)
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


async def governance_directory_records(db, admin):
    created = datetime.now(UTC) - timedelta(days=4)
    owners = [
        User(
            id=UUID(int=701),
            username="owner%_active",
            password_hash="unused",
            active=True,
        ),
        User(
            id=UUID(int=702),
            username="ownerXXdisabled",
            password_hash="unused",
            active=False,
        ),
    ]
    db.add_all(owners)
    await db.flush()
    workspaces = [
        Workspace(
            id=UUID(int=identity),
            name=name,
            created_by=owners[owner_index].id,
            state=state,
            created_at=created + timedelta(days=days),
            archived_at=created if state == "archived" else None,
            governance_frozen_at=created if frozen else None,
            governance_frozen_by=admin.id if frozen else None,
        )
        for identity, name, owner_index, state, frozen, days in [
            (801, "Governance space%_ Alpha", 0, "active", False, 0),
            (802, "Governance space%_ Beta", 0, "archived", True, 0),
            (803, "Governance spaceXX Other", 1, "active", True, 1),
            (804, "Governance Zeta", 1, "archived", False, 2),
        ]
    ]
    db.add_all(workspaces)
    await db.flush()
    db.add_all([
        WorkspaceMember(workspace_id=workspace.id, user_id=owners[index // 2].id, role="owner")
        for index, workspace in enumerate(workspaces)
    ])
    # A former member and a non-owner must not become additional owner search matches.
    db.add_all([
        WorkspaceMember(
            workspace_id=workspaces[2].id,
            user_id=owners[0].id,
            role="admin",
            state="active",
            terminated_at=created,
        ),
        WorkspaceMember(workspace_id=workspaces[0].id, user_id=owners[1].id, role="viewer"),
    ])
    await db.commit()
    return workspaces, owners


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
    page = response.json()
    assert page["total"] == 1 and page["limit"] == 20 and page["offset"] == 0
    assert any(row["id"] == str(fixture_workspace_id(admin)) for row in page["items"])
    await client.aclose()


@pytest.mark.anyio
async def test_admin_workspace_directory_filters_and_sorts_current_owners_in_sql(
    async_db, tmp_path, monkeypatch
):
    client, admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    workspaces, owners = await governance_directory_records(async_db, admin)
    try:
        response = await client.get(
            "/api/v1/admin/workspaces",
            params={"search": "Governance", "sort": "created", "limit": 1, "offset": 1},
        )
        assert response.status_code == 200
        page = response.json()
        assert (page["total"], page["limit"], page["offset"]) == (4, 1, 1)
        assert page["items"][0]["id"] == str(workspaces[1].id)
        assert datetime.fromisoformat(page["items"][0]["created_at"]) == workspaces[1].created_at
        assert page["items"][0]["owner_id"] == str(owners[0].id)

        filtered = await client.get(
            "/api/v1/admin/workspaces",
            params={
                "search": "Governance",
                "state": "active",
                "frozen": True,
                "owner_active": False,
            },
        )
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["id"] == str(workspaces[2].id)
        assert filtered.json()["items"][0]["owner_active"] is False
        assert filtered.json()["items"][0]["can_reassign_owner"] is False

        owner_order = await client.get(
            "/api/v1/admin/workspaces",
            params={"search": "Governance", "sort": "owner", "direction": "desc", "limit": 2},
        )
        assert owner_order.status_code == 200
        assert owner_order.json()["total"] == 4
        assert [row["id"] for row in owner_order.json()["items"]] == [
            str(workspaces[3].id),
            str(workspaces[2].id),
        ]
        empty = await client.get(
            "/api/v1/admin/workspaces",
            params={"search": "Governance", "state": "archived", "frozen": False, "offset": 100},
        )
        assert empty.status_code == 200
        assert empty.json()["items"] == [] and empty.json()["total"] == 1
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_workspace_search_escapes_wildcards_and_matches_both_identities(
    async_db, tmp_path, monkeypatch
):
    client, admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    workspaces, owners = await governance_directory_records(async_db, admin)
    try:
        for search in ["SPACE%_", "OWNER%_", str(owners[0].id)]:
            response = await client.get("/api/v1/admin/workspaces", params={"search": search})
            assert response.status_code == 200
            assert response.json()["total"] == 2
            assert [row["id"] for row in response.json()["items"]] == [
                str(workspaces[0].id),
                str(workspaces[1].id),
            ]
        identity = await client.get(
            "/api/v1/admin/workspaces", params={"search": str(workspaces[3].id)}
        )
        assert identity.status_code == 200
        assert identity.json()["total"] == 1
        assert identity.json()["items"][0]["id"] == str(workspaces[3].id)
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_can_read_selected_governance_target_without_workspace_membership(
    async_db, tmp_path, monkeypatch
):
    client, admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    workspaces, owners = await governance_directory_records(async_db, admin)
    try:
        response = await client.get(f"/api/v1/admin/workspaces/{workspaces[3].id}")
        assert response.status_code == 200
        target = response.json()
        assert target["owner_id"] == str(owners[1].id)
        assert target["owner_active"] is False
        assert target["state"] == "archived"
        assert target["can_reassign_owner"] is True
        missing = await client.get(f"/api/v1/admin/workspaces/{UUID(int=899)}")
        assert missing.status_code == 404
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_member_cannot_read_workspace_governance_directory_or_selected_target(
    async_db, tmp_path, monkeypatch
):
    client, member, _login = await member_client(async_db, tmp_path, monkeypatch)
    workspace = await provision_initial_workspace(async_db, member)
    await async_db.commit()
    try:
        for path in ["/api/v1/admin/workspaces", f"/api/v1/admin/workspaces/{workspace.id}"]:
            assert (await client.get(path)).status_code == 404
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_administrator_can_disable_owner_then_explicitly_reassign_workspace(
    async_db, tmp_path, monkeypatch
):
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
        workspace = next(row for row in directory["items"] if row["owner_id"] == owner_id)
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
async def test_admin_users_sort_filtered_pages_with_stable_ties(async_db, tmp_path, monkeypatch):
    client, _admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    created = datetime.now(UTC)
    async_db.add_all([
        User(
            id=UUID(int=index),
            username=f"directory-{name}",
            password_hash="unused",
            role="member",
            active=active,
            created_at=created,
        )
        for index, name, active in [(1, "zeta", True), (2, "alpha", True), (3, "beta", False)]
    ])
    await async_db.commit()
    try:
        params = {"search": "DIRECTORY", "role": "member", "active": True, "limit": 1}
        alphabetical = await client.get("/api/v1/admin/users", params=params)
        assert alphabetical.status_code == 200
        assert alphabetical.json()["total"] == 2
        assert alphabetical.json()["items"][0]["username"] == "directory-alpha"

        newest = await client.get(
            "/api/v1/admin/users",
            params={**params, "sort": "created", "direction": "desc", "offset": 1},
        )
        assert newest.status_code == 200
        assert newest.json()["total"] == 2
        assert newest.json()["items"][0]["id"] == str(UUID(int=1))

        identity = await client.get(
            "/api/v1/admin/users", params={"search": str(UUID(int=3)), "sort": "created"}
        )
        assert identity.status_code == 200
        assert identity.json()["total"] == 1
        assert identity.json()["items"][0]["username"] == "directory-beta"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_invitations_search_sort_and_role_keep_state_and_totals(
    async_db, tmp_path, monkeypatch
):
    client, admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    created = datetime.now(UTC)
    async_db.add_all([
        Invitation(
            id=UUID(int=index),
            username=f"directory-{name}",
            token_hash=token_hash(f"directory-invitation-{index}"),
            created_by=admin.id,
            role=role,
            created_at=created,
            expires_at=created + timedelta(days=days),
        )
        for index, name, role, days in [
            (1, "zeta", "member", 1),
            (2, "alpha", "member", 1),
            (3, "beta", "administrator", 2),
            (4, "expired", "member", -1),
        ]
    ])
    await async_db.commit()
    try:
        params = {"search": "DIRECTORY", "state": "pending", "role": "member", "limit": 1}
        alphabetical = await client.get(
            "/api/v1/admin/invitations", params={**params, "sort": "username", "direction": "asc"}
        )
        assert alphabetical.status_code == 200
        assert alphabetical.json()["total"] == 2
        assert alphabetical.json()["items"][0]["username"] == "directory-alpha"

        expiry = await client.get(
            "/api/v1/admin/invitations",
            params={**params, "sort": "expires", "direction": "asc", "offset": 1},
        )
        assert expiry.status_code == 200
        assert expiry.json()["total"] == 2
        assert expiry.json()["items"][0]["id"] == str(UUID(int=2))

        identity = await client.get(
            "/api/v1/admin/invitations", params={"search": str(UUID(int=3))}
        )
        assert identity.status_code == 200
        assert identity.json()["total"] == 1
        assert identity.json()["items"][0]["username"] == "directory-beta"
        empty = await client.get("/api/v1/admin/invitations", params={**params, "offset": 20})
        assert empty.status_code == 200
        assert empty.json()["total"] == 2
        assert empty.json()["items"] == []
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_audit_chronology_preserves_filtered_pagination(
    async_db, tmp_path, monkeypatch
):
    client, admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    created = datetime.now(UTC)
    async_db.add_all([
        AuditEvent(
            id=UUID(int=index),
            actor_id=admin.id,
            action="directory.test",
            target_type="instance",
            detail={"message": "directory history"},
            created_at=created,
        )
        for index in range(1, 4)
    ])
    await async_db.commit()
    try:
        params = {
            "actor_id": str(admin.id),
            "action": "directory.test",
            "target_type": "instance",
            "search": "history",
            "limit": 1,
        }
        oldest = await client.get("/api/v1/admin/audit", params={**params, "direction": "asc"})
        newest = await client.get("/api/v1/admin/audit", params=params)
        assert oldest.status_code == newest.status_code == 200
        assert oldest.json()["total"] == newest.json()["total"] == 3
        assert oldest.json()["items"][0]["id"] == str(UUID(int=1))
        assert newest.json()["items"][0]["id"] == str(UUID(int=3))
        second = await client.get(
            "/api/v1/admin/audit", params={**params, "direction": "asc", "offset": 1}
        )
        assert second.status_code == 200
        assert second.json()["items"][0]["id"] == str(UUID(int=2))
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_workflow_name_and_chronology_use_filtered_total(
    async_db, tmp_path, monkeypatch, fake_durable_operations
):
    client, _admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    now = datetime.now(UTC)
    for index, name, state in [
        (1, "operations.check_objects", "succeeded"),
        (2, "operations.check_objects", "failed"),
        (3, "operations.check_objects", "failed"),
        (4, "documents.check_objects", "failed"),
    ]:
        row = WorkflowSummary(
            id=f"workflow-{index}",
            name=name,
            state=state,
            raw_status="SUCCESS" if state == "succeeded" else "ERROR",
            queue_name="operations",
            executor_id=None,
            created_at=now + timedelta(seconds=index),
            updated_at=now + timedelta(seconds=index),
        )
        fake_durable_operations.workflows[row.id] = row
    try:
        response = await client.get(
            "/api/v1/admin/workflows",
            params={
                "name": " operations.check_objects ",
                "state": "failed",
                "direction": "asc",
                "limit": 1,
                "offset": 1,
            },
        )
        assert response.status_code == 200
        assert response.json()["total"] == 2
        assert [row["id"] for row in response.json()["items"]] == ["workflow-3"]
        empty = await client.get("/api/v1/admin/workflows", params={"name": "check_objects"})
        assert empty.status_code == 200
        assert empty.json()["total"] == 0
        assert empty.json()["items"] == []
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("section", "params"),
    [
        ("users", {"sort": "role"}),
        ("users", {"role": "editor"}),
        ("users", {"direction": "newest"}),
        ("invitations", {"sort": "state"}),
        ("invitations", {"role": "editor"}),
        ("invitations", {"direction": "newest"}),
        ("audit", {"direction": "newest"}),
        ("workflows", {"direction": "newest"}),
        ("workspaces", {"direction": "newest"}),
        ("workspaces", {"sort": "state"}),
        ("workspaces", {"state": "deleted"}),
        ("workspaces", {"owner_active": "unknown"}),
    ],
)
async def test_admin_directory_rejects_unsupported_ordering(
    async_db, tmp_path, monkeypatch, section, params
):
    client, _admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    try:
        response = await client.get(f"/api/v1/admin/{section}", params=params)
        assert response.status_code == 422
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("section", ["overview", "workflows", "workspaces"])
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
@pytest.mark.parametrize(
    ("endpoint", "allowed_action"),
    [("audit", SystemAction.audit_read), ("maintenance", SystemAction.storage_metrics_read)],
)
async def test_admin_endpoint_relies_only_on_its_concrete_action(
    async_db, tmp_path, monkeypatch, endpoint, allowed_action
):
    client, _user, _login = await member_client(async_db, tmp_path, monkeypatch)

    def allow_concrete_action_only(_role, action, *, relation="any"):
        return action is allowed_action and relation == "any"

    monkeypatch.setattr(
        "quirebase.access.authorization.system_action_allowed",
        allow_concrete_action_only,
    )
    try:
        response = await client.get(f"/api/v1/admin/{endpoint}")
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
async def test_admin_maintenance_metrics_preserve_latest_checks_without_reading_history(
    async_db, tmp_path, monkeypatch, fake_durable_operations
):
    client, _admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    checked = datetime.now(UTC) - timedelta(hours=2)
    cleaned = datetime.now(UTC) - timedelta(hours=1)
    async_db.add(
        MaintenanceSnapshot(
            id=1,
            status="failed",
            missing_count=2,
            error_count=2,
            errors=["Missing file A", "Missing file B"],
            checked_at=checked,
            cleanup_started_at=cleaned - timedelta(seconds=5),
            cleanup_checked_at=cleaned,
            cleanup_counts={"import_batches": 4, "audit_events": 20},
            cleanup_error=None,
        )
    )
    await async_db.commit()
    history = AsyncMock(side_effect=AssertionError("maintenance must not read workflow history"))
    monkeypatch.setattr(fake_durable_operations, "list", history)
    try:
        response = await client.get("/api/v1/admin/maintenance")
        assert response.status_code == 200
        metrics = response.json()
        assert "storage" not in metrics and "workflows" not in metrics
        assert metrics["items_count"] == 0
        assert metrics["database_allocated_bytes"] > 0
        assert metrics["integrity_status"] == "failed"
        assert metrics["missing_files_count"] == metrics["integrity_error_count"] == 2
        assert metrics["integrity_errors"] == ["Missing file A", "Missing file B"]
        assert datetime.fromisoformat(metrics["integrity_checked_at"]) == checked
        assert datetime.fromisoformat(metrics["cleanup_checked_at"]) == cleaned
        assert metrics["cleanup_counts"] == {"import_batches": 4, "audit_events": 20}
        assert metrics["cleanup_error"] is None
        assert {
            "workflow_history_count",
            "workflow_checkpoint_count",
            "datasource_checkpoint_count",
        } <= metrics.keys()
        history.assert_not_awaited()
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_maintenance_rejects_unauthenticated_reads(async_db, tmp_path, monkeypatch):
    client, _admin, _login = await admin_client(async_db, tmp_path, monkeypatch)
    client.cookies.clear()
    try:
        response = await client.get("/api/v1/admin/maintenance")
        assert response.status_code == 401
    finally:
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
