import pytest
from app_helpers import json_payload
from sqlalchemy import select

from quirebase.models import AuditEvent, SystemSetting, User, WorkspaceMember, WorkspaceRole
from quirebase.workspaces import create_workspace


@pytest.mark.anyio
@pytest.mark.parametrize(
    "policy,actor_role,assign_other",
    [
        ("members_allowed", "member", False),
        ("admins_only", "administrator", False),
        ("admins_only", "administrator", True),
    ],
)
async def test_workspace_creation_audits_authorizing_system_role(
    async_db, policy, actor_role, assign_other
):
    actor = User(username="creator", password_hash="unused", role=actor_role)
    owner = User(username="assigned-owner", password_hash="unused") if assign_other else actor
    async_db.add_all([actor, owner] if assign_other else [actor])
    async_db.add(SystemSetting(key="workspace_creation_policy", value=policy))
    await async_db.commit()

    workspace = await create_workspace(
        async_db,
        actor,
        "Research",
        owner_username=owner.username if policy == "admins_only" else None,
    )
    event = await async_db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "workspace.create", AuditEvent.target_id == str(workspace.id)
        )
    )
    assert event is not None
    assert event.actor_id == actor.id
    assert event.authorization_role == actor_role
    assert event.authorization_resource_action == "workspace.create"
    assert event.detail == json_payload({
        "owner_user_id": owner.id,
        "owner_workspace_role": "owner",
        "creation_policy": policy,
    })
    membership = await async_db.scalar(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id)
    )
    assert membership is not None
    assert membership.user_id == owner.id
    assert membership.role is WorkspaceRole.owner
