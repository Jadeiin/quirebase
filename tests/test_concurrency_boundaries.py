from __future__ import annotations

import pytest
from sqlalchemy import select
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.documents.workflows import _lock_upload_authority
from quirebase.models import Item, User, WorkspaceMember, WorkspaceRole
from quirebase.workspaces import terminate_workspace_member


async def _user(db, username: str) -> User:
    user = User(username=username, password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    return user


@pytest.mark.anyio
async def test_upload_finalizer_rechecks_revoked_membership(async_db):
    owner = await _user(async_db, "upload-owner")
    actor = await _user(async_db, "upload-actor")
    membership = WorkspaceMember(
        workspace_id=fixture_workspace_id(owner),
        user_id=actor.id,
        role=WorkspaceRole.editor,
        invited_by=owner.id,
    )
    item = Item(
        workspace_id=fixture_workspace_id(owner),
        title="Finalizer target",
        created_by=owner.id,
    )
    async_db.add_all([membership, item])
    await async_db.commit()

    await terminate_workspace_member(async_db, owner, fixture_workspace_id(owner), membership.id)

    with pytest.raises(ValueError, match="no longer writable"):
        await _lock_upload_authority(async_db, actor.id, fixture_workspace_id(owner), item.id)


@pytest.mark.anyio
async def test_membership_history_allows_rejoin_after_termination(async_db):
    owner = await _user(async_db, "history-owner")
    actor = await _user(async_db, "history-actor")
    first = WorkspaceMember(
        workspace_id=fixture_workspace_id(owner),
        user_id=actor.id,
        role=WorkspaceRole.viewer,
        invited_by=owner.id,
    )
    async_db.add(first)
    await async_db.commit()
    await terminate_workspace_member(async_db, owner, fixture_workspace_id(owner), first.id)
    second = WorkspaceMember(
        workspace_id=fixture_workspace_id(owner),
        user_id=actor.id,
        role=WorkspaceRole.reviewer,
        invited_by=owner.id,
    )
    async_db.add(second)
    await async_db.commit()

    rows = list(
        (
            await async_db.scalars(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == fixture_workspace_id(owner),
                    WorkspaceMember.user_id == actor.id,
                )
            )
        ).all()
    )
    assert len(rows) == 2
    assert sum(row.terminated_at is None for row in rows) == 1
