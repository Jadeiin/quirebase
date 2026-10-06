from datetime import UTC, datetime
from itertools import product

import pytest
from sqlalchemy import delete, select

from quirebase.access import (
    ResourceAction,
    discoverable_project_ids_query,
    require_project_context,
    require_project_discoverable,
    resolve_workspace_context,
)
from quirebase.core.errors import ResourceUnavailable, WorkspaceUnavailable
from quirebase.models import (
    Project,
    ProjectMember,
    ProjectParticipation,
    ProjectState,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.projects import update_project_settings


async def _assert_discovery_matrix(db, role, lifecycle):
    owner = User(username="discovery-owner", password_hash="unused")
    actor = (
        owner
        if role is WorkspaceRole.owner
        else User(username="discovery-actor", password_hash="unused")
    )
    db.add_all([owner] if actor is owner else [owner, actor])
    await db.flush()
    workspace = Workspace(name="Visibility", created_by=owner.id)
    foreign = Workspace(name="Foreign", created_by=owner.id)
    db.add_all([workspace, foreign])
    await db.flush()
    db.add_all([
        WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.owner),
        WorkspaceMember(workspace_id=foreign.id, user_id=owner.id, role=WorkspaceRole.owner),
    ])
    if actor is not owner:
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=actor.id, role=role))
    if lifecycle == "archived":
        workspace.state = WorkspaceState.archived
    elif lifecycle == "suspended":
        workspace.governance_suspended_at = datetime.now(UTC)

    cases = []
    for root, participation, participant, state in product(
        (workspace, foreign), ProjectParticipation, (False, True), ProjectState
    ):
        project = Project(
            workspace_id=root.id,
            name=f"{root.name}-{participation}-{participant}-{state}",
            created_by=owner.id,
            participation=participation,
            state=state,
        )
        db.add(project)
        cases.append((project, participant))
    await db.flush()
    for project, participant in cases:
        if participant:
            db.add(
                ProjectMember(
                    workspace_id=project.workspace_id, project_id=project.id, user_id=actor.id
                )
            )
    await db.commit()

    context = await resolve_workspace_context(db, actor, workspace.id)
    listed_ids = set((await db.scalars(discoverable_project_ids_query(context))).all())
    for project, participant in cases:
        # Independent domain expectations prevent two equally wrong implementations from passing.
        expected = (
            project.workspace_id == workspace.id
            and project.state is not ProjectState.deleted
            and (
                project.participation is not ProjectParticipation.managed
                or participant
                or role in {WorkspaceRole.owner, WorkspaceRole.admin}
            )
        )
        if expected:
            assert (await require_project_discoverable(db, context, project)).project is project
        else:
            with pytest.raises(ResourceUnavailable):
                await require_project_discoverable(db, context, project)
        assert (project.id in listed_ids) is expected, project.name

    workspace.state = WorkspaceState.deleted
    await db.commit()
    with pytest.raises(WorkspaceUnavailable):
        await resolve_workspace_context(db, actor, workspace.id)


@pytest.mark.anyio
@pytest.mark.parametrize("role", WorkspaceRole)
@pytest.mark.parametrize("lifecycle", ["active", "archived", "suspended"])
async def test_sqlite_project_collection_and_direct_discovery_agree(async_db, role, lifecycle):
    await _assert_discovery_matrix(async_db, role, lifecycle)


@pytest.mark.anyio
@pytest.mark.shared_postgres
@pytest.mark.parametrize("role", WorkspaceRole)
@pytest.mark.parametrize("lifecycle", ["active", "archived", "suspended"])
async def test_postgres_project_collection_and_direct_discovery_agree(
    postgres_sessions, role, lifecycle
):
    async with postgres_sessions() as db:
        await _assert_discovery_matrix(db, role, lifecycle)


@pytest.mark.anyio
async def test_participation_discovery_is_independent_of_governance_grants(async_db, monkeypatch):
    from quirebase.access import project_scope

    actor = User(username="participant-discovery", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace = Workspace(name="Participant discovery", created_by=actor.id)
    async_db.add(workspace)
    await async_db.flush()
    async_db.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.owner)
    )
    projects = [
        Project(
            workspace_id=workspace.id, name=value.value, participation=value, created_by=actor.id
        )
        for value in ProjectParticipation
    ]
    async_db.add_all(projects)
    await async_db.flush()
    async_db.add_all([
        ProjectMember(workspace_id=workspace.id, project_id=project.id, user_id=actor.id)
        for project in projects
    ])
    await async_db.commit()
    context = await resolve_workspace_context(async_db, actor, workspace.id)

    # Revoking the governance privilege cannot redefine workspace/open modes or
    # remove a managed participant's ordinary discovery.
    monkeypatch.setattr(project_scope, "action_allowed", lambda _ctx, _action: False)
    visible = set((await async_db.scalars(discoverable_project_ids_query(context))).all())
    for project in projects:
        assert project.id in visible
        await require_project_discoverable(async_db, context, project)

    secret = Project(
        workspace_id=workspace.id,
        name="Unjoined managed",
        created_by=actor.id,
        participation=ProjectParticipation.managed,
    )
    async_db.add(secret)
    await async_db.commit()
    assert secret.id not in set(
        (await async_db.scalars(discoverable_project_ids_query(context))).all()
    )
    with pytest.raises(ResourceUnavailable):
        await require_project_discoverable(async_db, context, secret)
    monkeypatch.setattr(project_scope, "action_allowed", lambda _ctx, _action: True)
    assert secret.id in set((await async_db.scalars(discoverable_project_ids_query(context))).all())
    await require_project_discoverable(async_db, context, secret)


@pytest.mark.anyio
@pytest.mark.shared_postgres
@pytest.mark.concurrency_case("participation-recheck")
@pytest.mark.parametrize("loader", ["command", "shared", "update"])
@pytest.mark.parametrize("initially_discoverable", [False, True])
async def test_locked_project_loaders_filter_then_recheck_participation(
    postgres_sessions, postgres_race, loader, initially_discoverable
):
    async with postgres_sessions() as db:
        owner = User(username="discovery-lock-owner", password_hash="unused")
        actor = User(username="discovery-lock-actor", password_hash="unused")
        db.add_all([owner, actor])
        await db.flush()
        workspace = Workspace(name="Locked discovery", created_by=owner.id)
        db.add(workspace)
        await db.flush()
        db.add_all([
            WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.owner),
            WorkspaceMember(workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.editor),
        ])
        project = Project(
            workspace_id=workspace.id,
            name="Original",
            created_by=owner.id,
            participation=ProjectParticipation.managed,
        )
        db.add(project)
        await db.flush()
        if initially_discoverable:
            db.add(
                ProjectMember(workspace_id=workspace.id, project_id=project.id, user_id=actor.id)
            )
        await db.commit()
        workspace_id, project_id, actor_id = workspace.id, project.id, actor.id

    async def load():
        async with postgres_race.session("caller") as db:
            actor = await db.get(User, actor_id)
            try:
                if loader == "command":
                    await update_project_settings(
                        db, actor, workspace_id, project_id, name="Rejected"
                    )
                else:
                    await require_project_context(
                        db,
                        actor,
                        workspace_id,
                        project_id,
                        ResourceAction.project_update,
                        lock=loader,
                    )
            except ResourceUnavailable:
                await db.rollback()
                return "not found"
            return "unexpectedly discoverable"

    async with postgres_race.session("governor") as db:
        await db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        if initially_discoverable:
            await db.execute(
                delete(ProjectMember).where(
                    ProjectMember.project_id == project_id, ProjectMember.user_id == actor_id
                )
            )
        postgres_race.start("load", load())
        if initially_discoverable:
            await postgres_race.wait_blocked("caller", "governor")
            await db.commit()
        assert await postgres_race.join("load") == "not found"
        # An undiscoverable caller finishes even while governance still holds the root lock.
        await db.rollback()

    async with postgres_sessions() as db:
        assert (await db.get(Project, project_id)).name == "Original"
