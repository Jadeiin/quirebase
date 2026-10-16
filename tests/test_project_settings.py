import pytest
from app_helpers import json_payload
from sqlalchemy import select
from test_http import authenticated_async_client
from workspace_helpers import fixture_membership_id, provision_initial_workspace

from quirebase.access import resolve_workspace_context
from quirebase.core.errors import WorkspaceMembershipRequired
from quirebase.models import (
    AuditEvent,
    ProjectParticipant,
    ProjectParticipation,
    User,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
)
from quirebase.projects import (
    add_project_participant,
    create_project,
    join_project,
    list_workspace_projects,
    open_project_workspace,
    update_project_settings,
)
from quirebase.web.api import projects as projects_api
from quirebase.workspaces import (
    accept_workspace_invitation,
    invite_workspace_member,
    reactivate_workspace_member,
    suspend_workspace_member,
    terminate_workspace_member,
)


@pytest.mark.anyio
@pytest.mark.shared_postgres
@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current in ProjectParticipation
        for target in ProjectParticipation
        if current is not target
    ],
)
async def test_participation_transitions_preserve_or_clear_membership_selections(
    persistence_db, current, target
):
    db = persistence_db
    owner = User(username="transition-owner", password_hash="unused")
    active = User(username="transition-active", password_hash="unused")
    suspended = User(username="transition-suspended", password_hash="unused")
    db.add_all([owner, active, suspended])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    memberships = [
        WorkspaceMember(workspace_id=workspace.id, user_id=active.id, role=WorkspaceRole.editor),
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=suspended.id,
            role=WorkspaceRole.viewer,
            state=WorkspaceMemberState.suspended,
        ),
    ]
    db.add_all(memberships)
    await db.commit()
    project = await create_project(db, owner, workspace.id, "Transition", current)
    if current is not ProjectParticipation.workspace:
        db.add_all([
            ProjectParticipant(
                workspace_id=workspace.id,
                project_id=project.id,
                workspace_member_id=member.id,
                user_id=member.user_id,
            )
            for member in memberships
        ])
        await db.commit()
    before = dict(
        (
            await db.execute(
                select(ProjectParticipant.user_id, ProjectParticipant.id).where(
                    ProjectParticipant.project_id == project.id
                )
            )
        ).all()
    )
    owner_member_id = await fixture_membership_id(db, workspace.id, owner.id)

    await update_project_settings(db, owner, workspace.id, project.id, participation=target)
    after = dict(
        (
            await db.execute(
                select(ProjectParticipant.user_id, ProjectParticipant.id).where(
                    ProjectParticipant.project_id == project.id
                )
            )
        ).all()
    )
    assert project.participation is target
    if target is ProjectParticipation.workspace:
        assert after == {}
    elif current is ProjectParticipation.workspace:
        assert set(after) == ({owner.id} if target is ProjectParticipation.open else set())
        if after:
            participant = await db.get(ProjectParticipant, after[owner.id])
            assert participant.workspace_member_id == owner_member_id
    else:
        assert after == before  # Includes the suspended membership's original row identity.

    event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "project.settings.update", AuditEvent.project_id == project.id
        )
    )
    assert event.detail["old"]["participation"] == current.value
    assert event.detail["new"]["participation"] == target.value
    if target is ProjectParticipation.workspace:
        await update_project_settings(db, owner, workspace.id, project.id, participation=current)
        selected = set(
            await db.scalars(
                select(ProjectParticipant.user_id).where(
                    ProjectParticipant.project_id == project.id
                )
            )
        )
        assert active.id not in selected and suspended.id not in selected


@pytest.mark.anyio
@pytest.mark.shared_postgres
async def test_participation_transition_rolls_back_with_its_audit_on_commit_failure(
    persistence_db, monkeypatch
):
    db = persistence_db
    owner = User(username="transition-rollback", password_hash="unused")
    db.add(owner)
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    project = await create_project(db, owner, workspace.id, "Rollback", ProjectParticipation.open)
    workspace_id, project_id = workspace.id, project.id
    participant_id = await db.scalar(
        select(ProjectParticipant.id).where(ProjectParticipant.project_id == project_id)
    )

    async def fail_commit():
        await db.flush()
        raise RuntimeError("commit aborted")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit aborted"):
        await update_project_settings(
            db, owner, workspace_id, project_id, participation=ProjectParticipation.workspace
        )
    await db.rollback()
    await db.refresh(project)
    assert project.participation is ProjectParticipation.open
    assert await db.get(ProjectParticipant, participant_id) is not None
    assert (
        await db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.action == "project.settings.update", AuditEvent.project_id == project_id
            )
        )
        is None
    )


@pytest.mark.anyio
async def test_metadata_patch_preserves_concurrent_participation_change(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await async_db.get(User, item.created_by)
    project = await create_project(
        async_db, owner, item.workspace_id, "Original", ProjectParticipation.open
    )
    project_id = project.id
    async with async_session_factory() as other_db:
        other_owner = await other_db.get(User, owner.id)
        await update_project_settings(
            other_db,
            other_owner,
            item.workspace_id,
            project_id,
            participation=ProjectParticipation.managed,
        )
    try:
        response = await client.patch(
            f"/api/v1/workspaces/{item.workspace_id}/projects/{project_id}",
            json=json_payload({"name": "Metadata only"}),
        )
        assert response.status_code == 200
        await async_db.refresh(project)
        assert project.name == "Metadata only"
        assert project.participation is ProjectParticipation.managed
        assert (
            await async_db.scalar(
                select(ProjectParticipant.id).where(ProjectParticipant.project_id == project_id)
            )
            is not None
        )
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body", [{}, {"name": None}, {"description": None}, {"participation": None}]
)
async def test_project_patch_rejects_empty_or_null_settings(
    async_db, async_session_factory, tmp_path, monkeypatch, body
):
    client, item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await async_db.get(User, item.created_by)
    project = await create_project(async_db, owner, item.workspace_id, "Unchanged")
    try:
        response = await client.patch(
            f"/api/v1/workspaces/{item.workspace_id}/projects/{project.id}", json=json_payload(body)
        )
        assert response.status_code == 422
        await async_db.refresh(project)
        assert project.name == "Unchanged"
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("participation", [ProjectParticipation.open, ProjectParticipation.managed])
async def test_suspension_retains_participation_but_termination_removes_it(
    async_db, async_session_factory, tmp_path, monkeypatch, participation
):
    client, item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    await client.aclose()
    owner = await async_db.get(User, item.created_by)
    target = User(username="participant", password_hash="unused")
    async_db.add(target)
    await async_db.flush()
    membership = WorkspaceMember(
        workspace_id=item.workspace_id, user_id=target.id, role=WorkspaceRole.viewer
    )
    async_db.add(membership)
    await async_db.commit()
    project = await create_project(
        async_db, owner, item.workspace_id, "Participation", participation
    )
    if participation is ProjectParticipation.managed:
        await add_project_participant(
            async_db, owner, item.workspace_id, project.id, target.username
        )
    else:
        await join_project(async_db, target, item.workspace_id, project.id)
    participant_id = await async_db.scalar(
        select(ProjectParticipant.id).where(
            ProjectParticipant.project_id == project.id, ProjectParticipant.user_id == target.id
        )
    )

    await suspend_workspace_member(async_db, owner, item.workspace_id, membership.id)
    assert await async_db.get(ProjectParticipant, participant_id) is not None
    with pytest.raises(WorkspaceMembershipRequired):
        await resolve_workspace_context(async_db, target, item.workspace_id)
    view = await open_project_workspace(
        async_db, await resolve_workspace_context(async_db, owner, item.workspace_id), project.id
    )
    assert target.id not in {participant.user_id for participant in view.active_participants}

    await reactivate_workspace_member(async_db, owner, item.workspace_id, membership.id)
    context = await resolve_workspace_context(async_db, target, item.workspace_id)
    assert (await open_project_workspace(async_db, context, project.id)).is_participating
    assert project.id in {
        p.id for p, _, _ in (await list_workspace_projects(async_db, context, view="mine"))[0]
    }

    await terminate_workspace_member(async_db, owner, item.workspace_id, membership.id)
    assert await async_db.get(ProjectParticipant, participant_id, populate_existing=True) is None
    _, token = await invite_workspace_member(
        async_db, owner, item.workspace_id, target.username, "viewer"
    )
    await accept_workspace_invitation(async_db, target, item.workspace_id, token)
    context = await resolve_workspace_context(async_db, target, item.workspace_id)
    assert project.id not in {
        p.id for p, _, _ in (await list_workspace_projects(async_db, context, view="mine"))[0]
    }
    if participation is ProjectParticipation.open:
        assert not (await open_project_workspace(async_db, context, project.id)).is_participating
    else:
        assert (await list_workspace_projects(async_db, context))[0] == []


@pytest.mark.anyio
async def test_added_participant_response_survives_post_commit_deactivation(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await async_db.get(User, item.created_by)
    target = User(username="added-participant", password_hash="unused")
    async_db.add(target)
    await async_db.flush()
    async_db.add(
        WorkspaceMember(
            workspace_id=item.workspace_id, user_id=target.id, role=WorkspaceRole.viewer
        )
    )
    await async_db.commit()
    project = await create_project(
        async_db, owner, item.workspace_id, "Managed", ProjectParticipation.managed
    )
    target_id, username = target.id, target.username

    async def add_then_deactivate(*args):
        result = await add_project_participant(*args)
        async with async_session_factory() as other_db:
            user = await other_db.get(User, target_id)
            user.active = False
            await other_db.commit()
        return result

    monkeypatch.setattr(projects_api, "add_project_participant_domain", add_then_deactivate)
    try:
        response = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/projects/{project.id}/participants",
            json=json_payload({"username": username}),
        )
        assert response.status_code == 200
        assert response.json() == json_payload({"user_id": target_id, "username": username})
        assert (
            await async_db.scalar(
                select(ProjectParticipant.id).where(
                    ProjectParticipant.project_id == project.id,
                    ProjectParticipant.user_id == target_id,
                )
            )
            is not None
        )
    finally:
        await client.aclose()
