from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from advanced_alchemy.types import GUID
from sqlalchemy import bindparam, select, text
from sqlalchemy.exc import IntegrityError
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


async def _assert_rejected(db, statement: str, parameters: dict[str, str | UUID]) -> None:
    query = text(statement).bindparams(
        *(
            bindparam(key, type_=GUID())
            for key, value in parameters.items()
            if isinstance(value, UUID)
        )
    )
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(query, parameters)


async def assert_closed_state_constraints(db) -> None:
    user = User(username="closed-states", password_hash="unused")
    db.add(user)
    await db.flush()
    workspace = await provision_initial_workspace(db, user)
    await db.commit()

    await _assert_rejected(
        db,
        "UPDATE workspaces SET state = :state WHERE id = :id",
        {"state": "unknown", "id": workspace.id},
    )
    await _assert_rejected(
        db,
        "INSERT INTO projects "
        "(id, workspace_id, name, description, created_by, state, participation, created_at, updated_at) "
        "VALUES (:id, :workspace_id, 'bad', '', :user_id, 'unknown', 'workspace', "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        {"id": uuid4(), "workspace_id": workspace.id, "user_id": user.id},
    )
    await _assert_rejected(
        db,
        "INSERT INTO workspace_members "
        "(id, workspace_id, user_id, role, state, invited_by, created_at, updated_at) "
        "VALUES (:id, :workspace_id, :user_id, 'invalid', 'active', :user_id, "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        {"id": uuid4(), "workspace_id": workspace.id, "user_id": user.id},
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
