"""Test-only Workspace IDs for fixtures that create a User and its Workspace."""

from __future__ import annotations

from sqlalchemy import select

from quirebase.models import User, Workspace, WorkspaceMember, WorkspaceMemberState, WorkspaceState
from quirebase.workspaces import provision_initial_workspace as create_onboarding_workspace

_fixture_workspace_ids: dict[str, str] = {}


async def provision_initial_workspace(db, user: User) -> Workspace:
    workspace = await create_onboarding_workspace(db, user)
    _fixture_workspace_ids[user.id] = workspace.id
    return workspace


def fixture_workspace_id(user: User) -> str:
    return _fixture_workspace_ids[user.id]


async def accessible_workspace_id(db, user: User) -> str:
    workspace_id = await db.scalar(
        select(Workspace.id)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.state == WorkspaceMemberState.active,
            WorkspaceMember.terminated_at.is_(None),
            Workspace.state != WorkspaceState.deleted,
        )
        .order_by(Workspace.created_at, Workspace.id)
        .limit(1)
    )
    assert workspace_id is not None
    return workspace_id


async def fixture_workspace_id_or_create(db, user: User) -> str:
    if workspace_id := _fixture_workspace_ids.get(user.id):
        return workspace_id
    existing = await db.scalar(
        select(Workspace.id)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.state == WorkspaceMemberState.active,
            WorkspaceMember.terminated_at.is_(None),
            Workspace.state != WorkspaceState.deleted,
        )
        .limit(1)
    )
    if existing is not None:
        _fixture_workspace_ids[user.id] = existing
        return existing
    return (await provision_initial_workspace(db, user)).id
