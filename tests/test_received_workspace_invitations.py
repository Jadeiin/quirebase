"""The recipient inbox is independent of membership and never replays admission."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app_helpers import authenticated_async_client
from sqlalchemy import func, select

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable, WorkspaceLifecycleError
from quirebase.models import (
    AuditEvent,
    LoginSession,
    User,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.workspaces import (
    accept_workspace_invitation_by_id,
    accept_workspace_invitation_by_token,
    get_received_workspace_invitation,
    invite_workspace_member,
    list_received_workspace_invitations,
    provision_initial_workspace,
    revoke_workspace_invitation,
    suspend_workspace_member,
    terminate_workspace_member,
)


async def _setup(db):
    owner = User(username="owner", password_hash="unused")
    recipient = User(username="recipient", password_hash="unused")
    other = User(username="other", password_hash="unused")
    db.add_all([owner, recipient, other])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    await db.commit()
    invitation, token = await invite_workspace_member(
        db, owner, workspace.id, recipient.username, WorkspaceRole.editor
    )
    return owner, recipient, other, workspace, invitation, token


@pytest.mark.anyio
async def test_inbox_is_recipient_only_paginated_and_contains_no_token(async_db):
    db = async_db
    owner, recipient, other, workspace, invitation, _ = await _setup(db)
    rows, total = await list_received_workspace_invitations(db, recipient, limit=1)
    assert total == 1 and len(rows) == 1
    view = rows[0]
    assert view.id == invitation.id
    assert view.workspace_name == workspace.name
    assert view.inviter_username == owner.username
    assert view.role.value == "editor"
    assert view.can_accept and not view.can_open and view.state == "pending"
    assert not hasattr(view, "token_hash")
    assert await list_received_workspace_invitations(db, recipient, limit=1, offset=9) == ([], 1)
    assert await list_received_workspace_invitations(db, other) == ([], 0)
    with pytest.raises(ResourceNotFound):
        await get_received_workspace_invitation(db, other, invitation.id)
    with pytest.raises(ResourceNotFound):
        await accept_workspace_invitation_by_id(db, other, invitation.id)
    with pytest.raises(ResourceNotFound):
        await accept_workspace_invitation_by_id(db, recipient, uuid4())


@pytest.mark.anyio
@pytest.mark.parametrize("first", ["id", "token"])
async def test_id_and_token_share_single_use_and_reconcile_lost_response(async_db, first):
    db = async_db
    _, recipient, _, workspace, invitation, token = await _setup(db)
    if first == "id":
        member = await accept_workspace_invitation_by_id(db, recipient, invitation.id)
        retry = accept_workspace_invitation_by_token(db, recipient, token)
    else:
        member = await accept_workspace_invitation_by_token(db, recipient, token)
        retry = accept_workspace_invitation_by_id(db, recipient, invitation.id)
    with pytest.raises(ResourceNotFound):
        await retry
    view = await get_received_workspace_invitation(db, recipient, invitation.id)
    assert view.state == "accepted" and view.can_open and not view.can_accept
    assert await list_received_workspace_invitations(db, recipient) == ([], 0)
    assert (
        await db.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == recipient.id,
            )
        )
        == 1
    )
    assert (
        await db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.action == "workspace.invitation.accept",
                AuditEvent.target_id == str(member.id),
            )
        )
        == 1
    )


@pytest.mark.anyio
@pytest.mark.parametrize("lifecycle", ["frozen", "archived"])
async def test_pending_inbox_retains_read_only_workspace_but_cannot_accept(async_db, lifecycle):
    db = async_db
    _, recipient, _, workspace, invitation, _ = await _setup(db)
    if lifecycle == "frozen":
        workspace.governance_frozen_at = datetime.now(UTC)
    else:
        workspace.state = WorkspaceState.archived
    await db.commit()
    rows, total = await list_received_workspace_invitations(db, recipient)
    assert total == 1 and not rows[0].can_accept
    assert rows[0].unavailable_reason == "workspace_read_only"
    with pytest.raises(WorkspaceLifecycleError):
        await accept_workspace_invitation_by_id(db, recipient, invitation.id)
    workspace.governance_frozen_at = None
    workspace.state = WorkspaceState.active
    await db.commit()
    assert (await get_received_workspace_invitation(db, recipient, invitation.id)).can_accept


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["expired", "revoked"])
async def test_unavailable_invitation_disappears_but_own_detail_explains_state(async_db, state):
    db = async_db
    owner, recipient, _, workspace, invitation, _ = await _setup(db)
    if state == "expired":
        invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    else:
        await revoke_workspace_invitation(db, owner, workspace.id, invitation.id)
    assert await list_received_workspace_invitations(db, recipient) == ([], 0)
    view = await get_received_workspace_invitation(db, recipient, invitation.id)
    assert view.state == state and not view.can_accept and not view.can_open
    with pytest.raises(ResourceNotFound):
        await accept_workspace_invitation_by_id(db, recipient, invitation.id)


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["suspend", "terminate"])
async def test_reconciliation_never_restores_access_or_old_membership_generation(async_db, action):
    db = async_db
    owner, recipient, _, workspace, invitation, _ = await _setup(db)
    member = await accept_workspace_invitation_by_id(db, recipient, invitation.id)
    command = suspend_workspace_member if action == "suspend" else terminate_workspace_member
    await command(db, owner, workspace.id, member.id)
    view = await get_received_workspace_invitation(db, recipient, invitation.id)
    assert view.state == "accepted" and not view.can_accept and not view.can_open
    with pytest.raises(ResourceNotFound):
        await accept_workspace_invitation_by_id(db, recipient, invitation.id)
    if action == "terminate":
        fresh, _ = await invite_workspace_member(
            db, owner, workspace.id, recipient.username, "viewer"
        )
        replacement = await accept_workspace_invitation_by_id(db, recipient, fresh.id)
        assert replacement.id != member.id
        assert replacement.role is WorkspaceRole.viewer


@pytest.mark.anyio
async def test_recipient_deactivation_rechecks_cached_actor(async_db, async_session_factory):
    db = async_db
    _, recipient, _, _, invitation, _ = await _setup(db)
    async with async_session_factory() as other_db:
        current = await other_db.get(User, recipient.id)
        current.active = False
        await other_db.commit()
    with pytest.raises(ResourceUnavailable):
        await list_received_workspace_invitations(db, recipient)
    with pytest.raises(ResourceNotFound):
        await accept_workspace_invitation_by_id(db, recipient, invitation.id)


@pytest.mark.anyio
async def test_recipient_http_requires_credentials_and_origin_without_workspace_access(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, item.created_by)
    recipient = User(username="http-recipient", password_hash="unused")
    db.add(recipient)
    await db.flush()
    invitation, token = await invite_workspace_member(
        db, owner, item.workspace_id, recipient.username, "reviewer"
    )
    base = "/api/v1/me/workspace-invitations"
    try:
        assert (await client.get(base)).json()["total"] == 0
        assert (await client.get(f"{base}/{invitation.id}")).status_code == 404
        assert (await client.post(f"{base}/{invitation.id}/accept")).status_code == 404
        raw = "recipient-session"
        db.add(
            LoginSession(
                token_hash=token_hash(raw),
                user_id=recipient.id,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await db.commit()
        client.cookies.set(get_settings().session_cookie, raw)
        assert (await client.get(f"/api/v1/workspaces/{item.workspace_id}")).status_code == 404
        page = await client.get(base, params={"limit": 1})
        assert page.status_code == 200 and page.json()["total"] == 1
        assert page.json()["items"][0]["can_accept"]
        assert "token" not in page.text
        assert (
            await client.post(
                f"{base}/{invitation.id}/accept", headers={"Origin": "https://elsewhere.test"}
            )
        ).status_code == 403
        response = await client.post(f"{base}/{invitation.id}/accept")
        assert response.status_code == 200 and response.json()["workspace_id"] == str(
            item.workspace_id
        )
        assert (await client.get(f"{base}/{invitation.id}")).json()["can_open"]
        assert (
            await client.post(f"/api/v1/workspace-invitations/{token}/accept")
        ).status_code == 404
        client.cookies.clear()
        for url, method in [
            (base, client.get),
            (f"{base}/{invitation.id}", client.get),
            (f"{base}/{invitation.id}/accept", client.post),
        ]:
            assert (await method(url)).status_code == 401
    finally:
        await client.aclose()
        get_settings.cache_clear()
