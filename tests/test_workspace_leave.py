"""Self-service departure ends exactly one membership generation and preserves content."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app_helpers import authenticated_async_client
from sqlalchemy import select

from quirebase.access import ResourceAction, require_workspace_membership, workspace_decisions
from quirebase.core.config import get_settings
from quirebase.core.errors import (
    PermissionDenied,
    ResourceNotFound,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
)
from quirebase.models import (
    AuditEvent,
    Item,
    Project,
    ProjectParticipant,
    User,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.workspaces import (
    accept_workspace_invitation_by_id,
    invite_workspace_member,
    leave_workspace,
    provision_initial_workspace,
    transfer_workspace_ownership,
)


@pytest.fixture(
    params=[
        pytest.param("async_session_factory", id="sqlite"),
        pytest.param("postgres_sessions", id="postgres", marks=pytest.mark.shared_postgres),
    ]
)
def leave_sessions(request):
    return request.getfixturevalue(request.param)


async def _setup(db, role=WorkspaceRole.viewer):
    owner = User(username="leave-owner", password_hash="unused")
    member = User(username="leave-member", password_hash="unused")
    db.add_all([owner, member])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    membership = WorkspaceMember(workspace_id=workspace.id, user_id=member.id, role=role)
    db.add(membership)
    await db.commit()
    return owner, member, workspace, membership


@pytest.mark.anyio
@pytest.mark.parametrize(
    "role",
    [WorkspaceRole.viewer, WorkspaceRole.reviewer, WorkspaceRole.editor, WorkspaceRole.admin],
)
async def test_leave_ends_own_generation_and_preserves_content(leave_sessions, role):
    async with leave_sessions() as db:
        owner, member, workspace, membership = await _setup(db, role)
        project = Project(workspace_id=workspace.id, created_by=owner.id, name="Shared project")
        item = Item(
            workspace_id=workspace.id,
            created_by=member.id,
            work={"type": "Document", "title": "Keep this"},
        )
        db.add_all([project, item])
        await db.flush()
        db.add(
            ProjectParticipant(
                workspace_id=workspace.id,
                project_id=project.id,
                user_id=member.id,
                workspace_member_id=membership.id,
            )
        )
        await db.commit()
        membership_id, workspace_id, item_id = membership.id, workspace.id, item.id
        projection = workspace_decisions(role, WorkspaceState.active)
        assert ResourceAction.workspace_member_leave in projection.allowed
        await leave_workspace(db, member, workspace_id, membership_id)
        assert membership.terminated_at is not None
        assert await db.scalar(select(ProjectParticipant.id)) is None
        assert (await db.get(Item, item_id)).created_by == member.id
        assert await db.get(Project, project.id) is not None
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "workspace.member.leave")
        )
        assert event.actor_id == member.id and event.target_id == str(membership_id)
        assert event.authorization_role == role.value
        assert event.authorization_resource_action == "workspace_member.leave"
        with pytest.raises(WorkspaceMembershipRequired):
            await require_workspace_membership(db, member, workspace_id)
        with pytest.raises(WorkspaceMembershipRequired):
            await leave_workspace(db, member, workspace_id, membership_id)
        assert (
            len(
                list(
                    await db.scalars(
                        select(AuditEvent).where(AuditEvent.action == "workspace.member.leave")
                    )
                )
            )
            == 1
        )


@pytest.mark.anyio
async def test_owner_must_transfer_and_old_departure_cannot_end_a_rejoin(leave_sessions):
    async with leave_sessions() as db:
        owner, member, workspace, membership = await _setup(db)
        owner_membership = (await require_workspace_membership(db, owner, workspace.id)).membership
        assert (
            ResourceAction.workspace_member_leave
            not in workspace_decisions(WorkspaceRole.owner, WorkspaceState.active).allowed
        )
        with pytest.raises(PermissionDenied, match="ownership"):
            await leave_workspace(db, owner, workspace.id, owner_membership.id)
        with pytest.raises(ResourceNotFound):
            await leave_workspace(db, member, workspace.id, owner_membership.id)
        await transfer_workspace_ownership(db, owner, workspace.id, membership.id)
        await leave_workspace(db, owner, workspace.id, owner_membership.id)
        invitation, _ = await invite_workspace_member(
            db, member, workspace.id, owner.username, "editor"
        )
        rejoined = await accept_workspace_invitation_by_id(db, owner, invitation.id)
        assert rejoined.id != owner_membership.id
        with pytest.raises(ResourceNotFound):
            await leave_workspace(db, owner, workspace.id, owner_membership.id)
        assert rejoined.terminated_at is None
        assert (
            await require_workspace_membership(db, owner, workspace.id)
        ).membership.id == rejoined.id


@pytest.mark.anyio
@pytest.mark.parametrize("blocked", ["archived", "frozen", "suspended", "inactive"])
async def test_leave_rechecks_current_lifecycle_and_authority(leave_sessions, blocked):
    async with leave_sessions() as db:
        _, member, workspace, membership = await _setup(db)
        if blocked == "archived":
            workspace.state = WorkspaceState.archived
        elif blocked == "frozen":
            workspace.governance_frozen_at = datetime.now(UTC)
        elif blocked == "suspended":
            membership.state = WorkspaceMemberState.suspended
        else:
            member.active = False
        await db.commit()
        error = (
            WorkspaceLifecycleError
            if blocked in {"archived", "frozen"}
            else WorkspaceMembershipRequired
        )
        with pytest.raises(error):
            await leave_workspace(db, member, workspace.id, membership.id)
        assert membership.terminated_at is None
        assert (
            await db.scalar(select(AuditEvent).where(AuditEvent.action == "workspace.member.leave"))
            is None
        )


@pytest.mark.anyio
async def test_leave_http_projects_own_generation_and_enforces_origin(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        member = await db.get(User, item.created_by)
        owner = User(username="new-workspace-owner", password_hash="unused")
        db.add(owner)
        await db.flush()
        target = WorkspaceMember(
            workspace_id=item.workspace_id, user_id=owner.id, role=WorkspaceRole.viewer
        )
        db.add(target)
        await db.commit()
        await transfer_workspace_ownership(db, member, item.workspace_id, target.id)
        base = f"/api/v1/workspaces/{item.workspace_id}"
        view = (await client.get(base)).json()
        assert "workspace_member.leave" in view["authorization"]["allowed"]
        body = {"membership_id": view["current_membership_id"]}
        assert (
            await client.post(
                f"{base}/leave", json=body, headers={"Origin": "https://elsewhere.test"}
            )
        ).status_code == 403
        assert (
            await client.post(f"{base}/leave", json={"membership_id": str(target.id)})
        ).status_code == 404
        assert (
            await client.post(f"{base}/leave", json={"membership_id": str(uuid4())})
        ).status_code == 404
        assert (await client.post(f"{base}/leave", json=body)).status_code == 200
        assert (await client.get(base)).status_code == 404
        assert (await client.post(f"{base}/leave", json=body)).status_code == 404
        client.cookies.clear()
        assert (await client.post(f"{base}/leave", json=body)).status_code == 401
    finally:
        await client.aclose()
        get_settings.cache_clear()
