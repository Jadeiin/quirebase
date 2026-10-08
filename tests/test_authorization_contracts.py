"""HTTP projections and commands must agree on lifecycle and discoverability."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from test_http import authenticated_async_client

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.models import (
    AnnotationScope,
    AuditEvent,
    LoginSession,
    PdfAnnotation,
    ProjectItem,
    ProjectParticipation,
    ProjectState,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.projects import create_project


async def _sign_in_member(db, client, workspace_id, role):
    actor = User(username="contract-actor", password_hash="unused")
    db.add(actor)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace_id, user_id=actor.id, role=role))
    raw = "contract-session"
    db.add(
        LoginSession(
            token_hash=token_hash(raw),
            user_id=actor.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.commit()
    client.cookies.set(get_settings().session_cookie, raw)


@pytest.mark.anyio
@pytest.mark.parametrize("role", WorkspaceRole)
@pytest.mark.parametrize("lifecycle", ["active", "archived", "frozen"])
@pytest.mark.parametrize("project_state", [ProjectState.active, ProjectState.archived])
async def test_resource_projections_match_commands_and_project_choices(
    async_db, async_session_factory, tmp_path, monkeypatch, role, lifecycle, project_state
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, item.created_by)
    project = await create_project(
        db, owner, item.workspace_id, "Original", ProjectParticipation.open
    )
    db.add(ProjectItem(workspace_id=item.workspace_id, project_id=project.id, item_id=item.id))
    if role is not WorkspaceRole.owner:
        await _sign_in_member(db, client, item.workspace_id, role)
    workspace = await db.get(Workspace, item.workspace_id)
    project.state = project_state
    if lifecycle == "archived":
        workspace.state = WorkspaceState.archived
    elif lifecycle == "frozen":
        workspace.governance_frozen_at = datetime.now(UTC)
    await db.commit()
    base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id
    capability = role in {WorkspaceRole.owner, WorkspaceRole.admin, WorkspaceRole.editor}
    workspace_writable = capability and lifecycle == "active"
    project_writable = workspace_writable and project_state is ProjectState.active
    choices = {"open", "workspace"} if workspace_writable else set()
    if workspace_writable and role in {WorkspaceRole.owner, WorkspaceRole.admin}:
        choices.add("managed")
    try:
        workspace_response = await client.get(base)
        assert workspace_response.status_code == 200
        workspace_view = workspace_response.json()
        assert (
            "project.update" in workspace_view["authorization"]["allowed"]
        ) == workspace_writable
        assert set(workspace_view["allowed_project_participations"]) == choices
        detail = await client.get(f"{base}/projects/{project.id}")
        assert detail.status_code == 200
        view = detail.json()
        assert ("project.update" in view["authorization"]["allowed"]) == project_writable
        assert set(view["allowed_participation_changes"]) == (
            choices if project_writable else set()
        )
        overview = await client.get(f"{base}/items/{item_id}/overview")
        assert overview.status_code == 200
        assert ("item.update" in overview.json()["authorization"]["allowed"]) == workspace_writable

        response = await client.patch(f"{base}/projects/{project.id}", json={"name": "Changed"})
        assert (response.status_code == 200) == project_writable
        if not project_writable:
            assert response.status_code in {403, 404, 409}
            await db.rollback()
        await db.refresh(project)
        assert project.name == ("Changed" if project_writable else "Original")
        events = list(
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "project.settings.update",
                    AuditEvent.project_id == project.id,
                )
            )
        )
        assert len(events) == int(project_writable)

        # Canonical Item authority is independent of the associated Project's state.
        await db.refresh(item)
        item_response = await client.put(
            f"{base}/items/{item_id}",
            json={"expected_version": item.version, "metadata": {"title": "Changed Item"}},
        )
        assert (item_response.status_code == 200) == workspace_writable
        if not workspace_writable:
            assert item_response.status_code in {403, 409}
        await db.refresh(item)
        assert item.title == ("Changed Item" if workspace_writable else "Paper")
        item_events = list(
            await db.scalars(
                select(AuditEvent.id).where(
                    AuditEvent.action == "item.update", AuditEvent.target_id == str(item_id)
                )
            )
        )
        assert len(item_events) == int(workspace_writable)
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_http_surfaces_hide_managed_project_without_hiding_canonical_item(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await db.get(User, item.created_by)
    projects = [
        await create_project(db, owner, item.workspace_id, name, mode)
        for name, mode in [
            ("Visible open", ProjectParticipation.open),
            ("Hidden managed", ProjectParticipation.managed),
        ]
    ]
    links = [
        ProjectItem(workspace_id=item.workspace_id, project_id=project.id, item_id=item.id)
        for project in projects
    ]
    db.add_all(links)
    await db.flush()
    annotations = [
        PdfAnnotation(
            workspace_id=item.workspace_id,
            item_id=item.id,
            file_revision_id=revision.id,
            project_item_id=link.id,
            author_id=owner.id,
            page_index=0,
            kind="note",
            scope=AnnotationScope.project,
            body=project.name,
            payload={"type": "note", "rect": {"x": 0, "y": 0, "width": 10, "height": 10}},
        )
        for project, link in zip(projects, links, strict=True)
    ]
    db.add_all(annotations)
    await db.commit()
    await _sign_in_member(db, client, item.workspace_id, WorkspaceRole.reviewer)
    base = f"/api/v1/workspaces/{item.workspace_id}"
    visible, hidden = projects
    try:
        for path in [
            f"/items/{item.id}",
            f"/items/{item.id}/overview",
            f"/items/{item.id}/organize",
            f"/items/{item.id}/annotations",
            f"/items/{item.id}/revisions/{revision.id}/viewer",
            "/items",
            "/projects?view=all",
            "/dashboard",
        ]:
            response = await client.get(base + path)
            assert response.status_code == 200, path
            assert str(hidden.id) not in response.text, path
            assert hidden.name not in response.text, path
        organize = (await client.get(f"{base}/items/{item.id}/organize")).json()
        assert organize["item"]["id"] == str(item.id)
        assert [(row["id"], row["assigned"]) for row in organize["projects"]] == [
            (str(visible.id), True)
        ]
        overview = (await client.get(f"{base}/items/{item.id}/overview")).json()
        assert overview["counts"]["annotations"] == 1
        annotation_view = (await client.get(f"{base}/items/{item.id}/annotations")).json()
        assert [row["id"] for row in annotation_view["annotations"]] == [str(annotations[0].id)]
        for path in [f"/projects/{hidden.id}", f"/items?project={hidden.id}"]:
            assert (await client.get(base + path)).status_code == 404
    finally:
        await client.aclose()
        get_settings.cache_clear()
