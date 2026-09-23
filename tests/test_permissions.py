import pytest
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.access.items import can_read_item
from quirebase.models import Item, User, WorkspaceMember, WorkspaceRole


async def _provisioned_user(db, username: str) -> User:
    user = User(username=username, password_hash="x")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    return user


@pytest.mark.anyio
async def test_item_access_is_workspace_membership_not_creator_or_project_membership(async_db):
    db = async_db
    owner = await _provisioned_user(db, "owner")
    member = await _provisioned_user(db, "member")
    outsider = await _provisioned_user(db, "outsider")
    workspace_id = fixture_workspace_id(owner)
    assert workspace_id is not None
    db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=member.id,
            role=WorkspaceRole.viewer,
            invited_by=owner.id,
        )
    )
    item = Item(workspace_id=workspace_id, title="Paper", created_by=owner.id)
    db.add(item)
    await db.commit()

    assert await can_read_item(db, owner, workspace_id, item.id)
    assert await can_read_item(db, member, workspace_id, item.id)
    assert not await can_read_item(db, outsider, workspace_id, item.id)
