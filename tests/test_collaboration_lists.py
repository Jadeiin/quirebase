"""Collaboration directories filter/count/page in SQL without changing discoverability."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from test_http import authenticated_async_client

from quirebase.access import resolve_workspace_context
from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.errors import PermissionDenied
from quirebase.models import (
    LoginSession,
    Project,
    ProjectParticipant,
    ProjectParticipation,
    ProjectState,
    User,
    WorkspaceInvitation,
    WorkspaceInvitationRole,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
)
from quirebase.projects import list_workspace_projects
from quirebase.workspaces import (
    list_workspace_governance_members,
    list_workspace_invitations,
    list_workspace_members,
    provision_initial_workspace,
)


async def _directory(db):
    owner = User(username="owner", password_hash="unused")
    editor = User(username="editor", password_hash="unused")
    db.add_all([owner, editor])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    membership = WorkspaceMember(
        workspace_id=workspace.id, user_id=editor.id, role=WorkspaceRole.editor
    )
    db.add(membership)
    await db.commit()
    return owner, editor, workspace, membership


@pytest.mark.anyio
async def test_project_filters_sort_and_count_preserve_participation_discovery(async_db):
    db = async_db
    owner, editor, workspace, membership = await _directory(db)
    date = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for identity, name, participation, state in [
        (10, "Alpha", "workspace", "active"),
        (20, "Beta", "open", "active"),
        (30, "Beta", "open", "active"),
        (40, "Hidden", "managed", "active"),
        (50, "Selected", "managed", "active"),
        (60, "Archive", "workspace", "archived"),
        (70, "Archive", "open", "archived"),
    ]:
        project = Project(
            id=UUID(int=identity),
            workspace_id=workspace.id,
            created_by=owner.id,
            name=name,
            participation=ProjectParticipation(participation),
            state=ProjectState(state),
            created_at=date,
            updated_at=date + timedelta(days=identity),
        )
        rows.append(project)
        db.add(project)
    await db.flush()
    for project in (rows[1], rows[4]):
        db.add(
            ProjectParticipant(
                workspace_id=workspace.id,
                project_id=project.id,
                workspace_member_id=membership.id,
                user_id=editor.id,
            )
        )
    await db.commit()
    context = await resolve_workspace_context(db, editor, workspace.id)
    page, total = await list_workspace_projects(db, context, sort="created", limit=2, offset=1)
    assert total == 6
    assert [project.id.int for project, _, _ in page] == [20, 30]
    page, total = await list_workspace_projects(
        db, context, state="active", sort="updated", direction="desc", limit=2
    )
    assert total == 4
    assert [project.id.int for project, _, _ in page] == [50, 30]
    page, total = await list_workspace_projects(
        db, context, view="mine", sort="created", direction="desc"
    )
    assert total == 4
    assert [project.id.int for project, _, _ in page] == [60, 50, 20, 10]
    assert all(participating for _, _, participating in page)
    page, total = await list_workspace_projects(db, context, view="joinable")
    assert total == 1 and page[0][0].id.int == 30 and not page[0][2]
    assert await list_workspace_projects(db, context, view="joinable", state="archived") == ([], 0)
    page, total = await list_workspace_projects(
        db, context, search=" BETA ", sort="name", direction="desc", limit=1
    )
    assert total == 2 and page[0][0].id.int == 30
    assert await list_workspace_projects(db, context, search="beta", offset=10) == ([], 2)
    owner_context = await resolve_workspace_context(db, owner, workspace.id)
    page, total = await list_workspace_projects(db, owner_context, search="hidden")
    assert total == 1 and page[0][0].id.int == 40 and not page[0][2]


@pytest.mark.anyio
async def test_member_filters_keep_directory_and_governance_visibility_distinct(async_db):
    db = async_db
    owner, editor, workspace, _ = await _directory(db)
    joined = datetime(2026, 1, 1, tzinfo=UTC)
    for identity, username, active, state, terminated in [
        (10, "candidate-a", True, "active", False),
        (20, "candidate-z", True, "active", False),
        (30, "candidate-disabled", False, "active", False),
        (40, "candidate-suspended", True, "suspended", False),
        (50, "candidate-terminated", True, "active", True),
    ]:
        user = User(username=username, password_hash="unused", active=active)
        db.add(user)
        await db.flush()
        db.add(
            WorkspaceMember(
                id=UUID(int=identity),
                workspace_id=workspace.id,
                user_id=user.id,
                role=WorkspaceRole.viewer,
                state=WorkspaceMemberState(state),
                created_at=joined,
                terminated_at=joined if terminated else None,
            )
        )
    await db.commit()
    context = await resolve_workspace_context(db, owner, workspace.id)
    page, total = await list_workspace_members(
        db, context, search="CANDIDATE", role=WorkspaceRole.viewer, direction="desc", limit=1
    )
    assert total == 2 and page[0].id.int == 20
    assert await list_workspace_members(
        db, context, search="candidate", role=WorkspaceRole.viewer, offset=10
    ) == ([], 2)
    page, total = await list_workspace_governance_members(
        db,
        context,
        search="candidate",
        role=WorkspaceRole.viewer,
        state=WorkspaceMemberState.active,
        sort="joined",
        direction="desc",
        limit=2,
    )
    assert total == 3 and [member.id.int for member in page] == [30, 20]
    page, total = await list_workspace_governance_members(
        db, context, role=WorkspaceRole.viewer, state=WorkspaceMemberState.suspended
    )
    assert total == 1 and page[0].id.int == 40
    assert await list_workspace_governance_members(
        db, context, search="candidate", role=WorkspaceRole.viewer, offset=10
    ) == ([], 4)
    editor_context = await resolve_workspace_context(db, editor, workspace.id)
    with pytest.raises(PermissionDenied):
        await list_workspace_governance_members(db, editor_context, role=WorkspaceRole.viewer)
    with pytest.raises(PermissionDenied):
        await list_workspace_invitations(db, editor_context)


async def _invitations(db, owner, workspace_id):
    now = datetime.now(UTC)
    created = now - timedelta(days=1)
    for identity, username, role, state in [
        (10, "candidate-z", "viewer", "pending"),
        (20, "candidate-a", "viewer", "pending"),
        (30, "candidate-editor", "editor", "pending"),
        (40, "candidate-accepted", "viewer", "accepted"),
        (50, "candidate-revoked", "viewer", "revoked"),
        (60, "candidate-expired", "viewer", "expired"),
    ]:
        user = User(username=username, password_hash="unused")
        db.add(user)
        await db.flush()
        db.add(
            WorkspaceInvitation(
                id=UUID(int=identity),
                workspace_id=workspace_id,
                user_id=user.id,
                invited_by=owner.id,
                role=WorkspaceInvitationRole(role),
                token_hash=token_hash(str(identity)),
                created_at=created,
                expires_at=now - timedelta(hours=1)
                if state == "expired"
                else now + timedelta(days=identity),
                accepted_at=now if state == "accepted" else None,
                revoked_at=now if state == "revoked" else None,
            )
        )
    await db.commit()


@pytest.mark.anyio
async def test_pending_invitation_filters_sort_page_and_total(async_db):
    db = async_db
    owner, editor, workspace, _ = await _directory(db)
    await _invitations(db, owner, workspace.id)
    context = await resolve_workspace_context(db, owner, workspace.id)
    page, total = await list_workspace_invitations(db, context, limit=2)
    assert total == 3 and [invitation.id.int for invitation in page] == [30, 20]
    page, total = await list_workspace_invitations(
        db, context, search=" CANDIDATE ", role="viewer", sort="username", direction="asc", limit=1
    )
    assert total == 2 and page[0].id.int == 20
    page, total = await list_workspace_invitations(db, context, sort="expires", direction="asc")
    assert total == 3 and [invitation.id.int for invitation in page] == [10, 20, 30]
    assert await list_workspace_invitations(db, context, role="viewer", offset=10) == ([], 2)
    assert await list_workspace_invitations(db, context, search="candidate-") == (page[::-1], 3)
    assert await list_workspace_invitations(db, context, search="%") == ([], 0)
    other = await provision_initial_workspace(db, editor)
    await db.commit()
    assert await list_workspace_invitations(
        db, await resolve_workspace_context(db, editor, other.id)
    ) == ([], 0)


@pytest.mark.anyio
async def test_collaboration_http_contracts_and_governance_authority(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, item.created_by)
    await _invitations(db, owner, item.workspace_id)
    base = f"/api/v1/workspaces/{item.workspace_id}"
    try:
        response = await client.get(
            f"{base}/invitations",
            params={"role": "viewer", "sort": "username", "direction": "asc", "limit": 1},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2 and body["limit"] == 1 and body["offset"] == 0
        assert body["items"][0]["username"] == "candidate-a"
        assert "token" not in response.text
        created = await client.post(
            f"{base}/projects", json={"name": "Directory dates", "participation": "workspace"}
        )
        assert created.status_code == 201
        project_page = await client.get(
            f"{base}/projects", params={"state": "active", "sort": "updated", "direction": "desc"}
        )
        project = project_page.json()["items"][0]
        assert project["created_at"] and project["updated_at"]
        detail = await client.get(f"{base}/projects/{created.json()['id']}")
        assert detail.json()["created_at"] == project["created_at"]
        for path, parameters in [
            ("projects", {"sort": "wrong"}),
            ("projects", {"state": "wrong"}),
            ("members", {"role": "wrong"}),
            ("members", {"direction": "wrong"}),
            ("governance/members", {"state": "wrong"}),
            ("governance/members", {"sort": "wrong"}),
            ("invitations", {"role": "owner"}),
            ("invitations", {"sort": "wrong"}),
            ("invitations", {"limit": 101}),
        ]:
            assert (await client.get(f"{base}/{path}", params=parameters)).status_code == 422
        viewer = User(username="directory-viewer", password_hash="unused")
        db.add(viewer)
        await db.flush()
        db.add_all([
            WorkspaceMember(
                workspace_id=item.workspace_id, user_id=viewer.id, role=WorkspaceRole.viewer
            ),
            LoginSession(
                token_hash=token_hash("directory-session"),
                user_id=viewer.id,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
        ])
        await db.commit()
        client.cookies.set(get_settings().session_cookie, "directory-session")
        directory = await client.get(f"{base}/members", params={"role": "viewer"})
        assert directory.status_code == 200 and directory.json()["total"] == 1
        assert set(directory.json()["items"][0]) == {"user_id", "username", "role"}
        assert (await client.get(f"{base}/governance/members")).status_code == 403
        assert (await client.get(f"{base}/invitations")).status_code == 403
    finally:
        await client.aclose()
        get_settings.cache_clear()
