from __future__ import annotations

import pytest
from test_public_api import api_client, bearer
from workspace_helpers import provision_initial_workspace

from quirebase.accounts import create_api_token
from quirebase.models import (
    Item,
    Project,
    ProjectItem,
    ProjectParticipation,
    ProjectState,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)


@pytest.mark.anyio
async def test_workspace_pages_preserve_access_totals_and_resolve_later_roots(
    async_db, async_session_factory
):
    owner = User(username="workspace-page-owner", password_hash="unused")
    stranger = User(username="workspace-page-stranger", password_hash="unused")
    async_db.add_all([owner, stranger])
    await async_db.flush()
    roots = []
    for index in range(29):
        root = Workspace(name=f"Workspace {index:02d}", created_by=owner.id)
        async_db.add(root)
        await async_db.flush()
        async_db.add(
            WorkspaceMember(
                workspace_id=root.id,
                user_id=owner.id,
                role=WorkspaceRole.editor if index == 27 else WorkspaceRole.owner,
                state=WorkspaceMemberState.suspended
                if index == 27
                else WorkspaceMemberState.active,
            )
        )
        if index == 27:
            async_db.add(
                WorkspaceMember(workspace_id=root.id, user_id=stranger.id, role=WorkspaceRole.owner)
            )
        roots.append(root)
    roots[26].state = WorkspaceState.archived
    roots[28].state = WorkspaceState.deleted
    await provision_initial_workspace(async_db, stranger)
    await async_db.commit()
    grant = await create_api_token(async_db, owner, "Workspace directory", expires_in_days=1)
    async with api_client(async_session_factory) as (client, _):
        headers = bearer(grant.raw_token)
        first = (await client.get("/api/v1/workspaces", headers=headers)).json()
        second = (await client.get("/api/v1/workspaces?offset=25", headers=headers)).json()
        empty = (await client.get("/api/v1/workspaces?offset=100", headers=headers)).json()
        assert [len(page["items"]) for page in (first, second, empty)] == [25, 2, 0]
        assert {page["total"] for page in (first, second, empty)} == {27}
        assert first["limit"] == 25 and second["offset"] == 25
        assert second["items"][-1]["state"] == "archived"
        current_id = str(roots[26].id)
        assert current_id not in {root["id"] for root in first["items"]}
        current = await client.get(f"/api/v1/workspaces/{current_id}", headers=headers)
        assert current.status_code == 200
        assert current.json()["id"] == current_id
        search = (await client.get("/api/v1/workspaces?search=26", headers=headers)).json()
        assert search["total"] == 1 and search["items"][0]["id"] == current_id
        assert (
            await client.get("/api/v1/workspaces?limit=101", headers=headers)
        ).status_code == 422
        assert (
            await client.get("/api/v1/workspaces?offset=-1", headers=headers)
        ).status_code == 422


@pytest.mark.anyio
async def test_project_pages_count_authorized_roots_and_separate_governance_from_participation(
    async_db, async_session_factory
):
    owner = User(username="project-page-owner", password_hash="unused")
    editor = User(username="project-page-editor", password_hash="unused")
    async_db.add_all([owner, editor])
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, owner)
    other = await provision_initial_workspace(async_db, editor)
    async_db.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=editor.id, role=WorkspaceRole.editor)
    )
    roots = [
        Project(
            workspace_id=workspace.id,
            name=f"Open {index:02d}",
            created_by=owner.id,
            participation=ProjectParticipation.open,
        )
        for index in range(26)
    ]
    managed = Project(
        workspace_id=workspace.id,
        name="Managed",
        created_by=owner.id,
        participation=ProjectParticipation.managed,
    )
    implicit = Project(workspace_id=workspace.id, name="Workspace", created_by=owner.id)
    async_db.add_all([
        *roots,
        managed,
        implicit,
        Project(
            workspace_id=workspace.id,
            name="Deleted",
            created_by=owner.id,
            state=ProjectState.deleted,
        ),
        Project(workspace_id=other.id, name="Foreign", created_by=editor.id),
    ])
    items = [
        Item(workspace_id=workspace.id, title=f"Item {index}", created_by=owner.id)
        for index in range(3)
    ]
    async_db.add_all(items)
    await async_db.flush()
    async_db.add_all([
        ProjectItem(
            workspace_id=workspace.id,
            project_id=roots[0].id,
            item_id=item.id,
            added_by=owner.id,
        )
        for item in items
    ])
    await async_db.commit()
    owner_grant = await create_api_token(async_db, owner, "Project directory", expires_in_days=1)
    editor_grant = await create_api_token(async_db, editor, "Project directory", expires_in_days=1)
    base = f"/api/v1/workspaces/{workspace.id}/projects"
    async with api_client(async_session_factory) as (client, _):
        headers = bearer(owner_grant.raw_token)
        first = (await client.get(base, headers=headers)).json()
        last = (await client.get(base + "?offset=25", headers=headers)).json()
        empty = (await client.get(base + "?offset=100", headers=headers)).json()
        assert [len(page["items"]) for page in (first, last, empty)] == [25, 3, 0]
        assert {page["total"] for page in (first, last, empty)} == {28}
        assert len({row["id"] for page in (first, last) for row in page["items"]}) == 28
        open_row = next(row for row in first["items"] if row["id"] == str(roots[0].id))
        assert open_row["item_count"] == 3
        governance = next(row for row in first["items"] if row["id"] == str(managed.id))
        assert governance["is_participating"] is False
        mine = (await client.get(base + "?view=mine", headers=headers)).json()
        assert mine["total"] == 1 and mine["items"][0]["id"] == str(implicit.id)
        joinable = (await client.get(base + "?view=joinable&offset=25", headers=headers)).json()
        assert joinable["total"] == 26 and len(joinable["items"]) == 1
        editor_headers = bearer(editor_grant.raw_token)
        directory = (await client.get(base + "?offset=100", headers=editor_headers)).json()
        assert directory["total"] == 27
        hidden = (await client.get(base + "?search=Managed", headers=editor_headers)).json()
        assert hidden["items"] == [] and hidden["total"] == 0
        assert (await client.get(base + "?limit=0", headers=headers)).status_code == 422
