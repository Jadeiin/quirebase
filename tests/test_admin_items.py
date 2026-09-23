from __future__ import annotations

import pytest
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.errors import ResourceNotFound, WorkspaceMembershipRequired
from quirebase.library import get_storage_metrics
from quirebase.models import User
from quirebase.workspaces import (
    list_workspaces_for_governance,
    read_workspace_items_break_glass,
)


async def _user(db, username: str, *, administrator: bool = False) -> User:
    user = User(
        username=username,
        password_hash="unused",
        role="administrator" if administrator else "member",
    )
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    return user


@pytest.mark.anyio
async def test_instance_admin_can_list_tenancy_metadata_without_membership(async_db):
    owner = await _user(async_db, "governance-owner")
    admin = await _user(async_db, "governance-admin", administrator=True)

    workspaces = await list_workspaces_for_governance(async_db, admin)

    assert fixture_workspace_id(owner) in {workspace.id for workspace in workspaces}


@pytest.mark.anyio
async def test_non_admin_cannot_use_break_glass(async_db):
    owner = await _user(async_db, "ordinary-owner")

    with pytest.raises(ResourceNotFound):
        await read_workspace_items_break_glass(
            async_db,
            owner,
            fixture_workspace_id(owner),
            "Attempted administrative content inspection",
        )


@pytest.mark.anyio
async def test_storage_metrics_remain_instance_metadata(async_db):
    admin = await _user(async_db, "metrics-admin", administrator=True)

    metrics = await get_storage_metrics(async_db, admin)

    assert metrics["items_count"] == 0
    assert metrics["total_disk_bytes"] == 0


@pytest.mark.anyio
async def test_admin_has_no_ordinary_workspace_content_authority(async_db):
    from quirebase.access import Capability, require_workspace_capability

    owner = await _user(async_db, "content-owner")
    admin = await _user(async_db, "content-admin", administrator=True)

    with pytest.raises(WorkspaceMembershipRequired):
        await require_workspace_capability(
            async_db, admin, fixture_workspace_id(owner), Capability.workspace_read
        )
