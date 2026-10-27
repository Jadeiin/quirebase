from __future__ import annotations

import pytest
from sqlalchemy import select
from state_contracts import assert_closed_state_constraints
from workspace_helpers import provision_initial_workspace

from quirebase.models import (
    Project,
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
async def test_closed_domain_states_are_loaded_as_domain_types(async_db):
    user = User(username="domain-types", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, user)
    project = Project(
        workspace_id=workspace.id,
        name="Typed",
        created_by=user.id,
        state=ProjectState.active,
        participation=ProjectParticipation.workspace,
    )
    async_db.add(project)
    await async_db.commit()
    async_db.expunge_all()

    loaded_workspace = await async_db.get(Workspace, workspace.id)
    loaded_project = await async_db.get(Project, project.id)
    membership = await async_db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id,
        )
    )

    assert loaded_workspace is not None and loaded_workspace.state is WorkspaceState.active
    assert loaded_project is not None and loaded_project.state is ProjectState.active
    assert loaded_project.participation is ProjectParticipation.workspace
    assert membership is not None and membership.role is WorkspaceRole.owner
    assert membership.state is WorkspaceMemberState.active


@pytest.mark.anyio
async def test_database_rejects_invalid_closed_states(async_db):
    await assert_closed_state_constraints(async_db)
