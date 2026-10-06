"""State-setting retries must retain authority checks and record only actual transitions."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from quirebase.core.errors import PermissionDenied, ResourceNotFound
from quirebase.core.timezones import as_utc
from quirebase.models import (
    AuditEvent,
    ProjectState,
    User,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
)
from quirebase.projects import create_project, set_project_state
from quirebase.workspaces import (
    invite_workspace_member,
    provision_initial_workspace,
    reactivate_workspace_member,
    recover_workspace_governance,
    revoke_workspace_invitation,
    set_workspace_member_role,
    suspend_workspace_governance,
    suspend_workspace_member,
    terminate_workspace_member,
)


@pytest.fixture(
    params=[
        pytest.param("async_session_factory", id="sqlite"),
        pytest.param("postgres_sessions", id="postgres", marks=pytest.mark.shared_postgres),
    ]
)
def command_sessions(request):
    return request.getfixturevalue(request.param)


async def _members(db):
    owner = User(username="command-owner", password_hash="unused", role="administrator")
    target = User(username="command-target", password_hash="unused")
    db.add_all([owner, target])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    member = WorkspaceMember(
        workspace_id=workspace.id, user_id=target.id, role=WorkspaceRole.viewer
    )
    db.add(member)
    await db.commit()
    return owner, target, workspace, member


async def _event_count(db, action, target_id):
    return await db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == action, AuditEvent.target_id == target_id)
    )


@pytest.mark.anyio
async def test_project_state_retries_have_one_effect_and_still_require_authority(command_sessions):
    async with command_sessions() as db:
        owner, target, workspace, _ = await _members(db)
        project = await create_project(db, owner, workspace.id, "Retry lifecycle")
        owner_id, target_id, workspace_id, project_id = (
            owner.id,
            target.id,
            workspace.id,
            project.id,
        )
        await set_project_state(db, owner, workspace.id, project.id, ProjectState.active)
        assert await _event_count(db, "project.active", project.id) == 0
        for state in (ProjectState.archived, ProjectState.active):
            owner, target = await db.get(User, owner_id), await db.get(User, target_id)
            await set_project_state(db, owner, workspace_id, project_id, state)
            await set_project_state(db, owner, workspace_id, project_id, state)
            assert await _event_count(db, f"project.{state.value}", project_id) == 1
            with pytest.raises(PermissionDenied):
                await set_project_state(db, target, workspace_id, project_id, state)
            await db.rollback()


@pytest.mark.anyio
async def test_member_retries_preserve_timestamps_audits_and_terminal_state(command_sessions):
    async with command_sessions() as db:
        owner, target, workspace, member = await _members(db)
        owner_id, target_id, workspace_id, member_id = owner.id, target.id, workspace.id, member.id
        await reactivate_workspace_member(db, owner, workspace_id, member_id)
        assert await _event_count(db, "workspace.member.reactivate", member_id) == 0
        await suspend_workspace_member(db, owner, workspace_id, member_id)
        suspended_at = as_utc(member.suspended_at)
        await suspend_workspace_member(db, owner, workspace_id, member_id)
        assert as_utc(member.suspended_at) == suspended_at
        assert await _event_count(db, "workspace.member.suspend", member_id) == 1
        await reactivate_workspace_member(db, owner, workspace_id, member_id)
        await reactivate_workspace_member(db, owner, workspace_id, member_id)
        assert member.suspended_at is None
        assert await _event_count(db, "workspace.member.reactivate", member_id) == 1
        await set_workspace_member_role(db, owner, workspace_id, member_id, WorkspaceRole.editor)
        await set_workspace_member_role(db, owner, workspace_id, member_id, WorkspaceRole.editor)
        assert await _event_count(db, "workspace.member.role", member_id) == 1
        with pytest.raises(PermissionDenied):
            await reactivate_workspace_member(db, target, workspace_id, member_id)
        await db.rollback()
        owner = await db.get(User, owner_id)
        await terminate_workspace_member(db, owner, workspace_id, member_id)
        with pytest.raises(ResourceNotFound):
            await reactivate_workspace_member(db, owner, workspace_id, member_id)
        await db.rollback()
        assert (await db.get(WorkspaceMember, member_id)).terminated_at is not None
        assert (await db.get(User, target_id)).active


@pytest.mark.anyio
async def test_member_retry_reloads_state_changed_by_another_session(command_sessions):
    async with command_sessions() as db:
        owner, _, workspace, member = await _members(db)
        owner_id, workspace_id, member_id = owner.id, workspace.id, member.id
        async with command_sessions() as other:
            await suspend_workspace_member(
                other, await other.get(User, owner_id), workspace_id, member_id
            )
        # The original identity map still says active. It must not turn reactivation into a no-op.
        assert member.state is WorkspaceMemberState.active
        await reactivate_workspace_member(db, owner, workspace_id, member_id)
        async with command_sessions() as fresh:
            assert (
                await fresh.get(WorkspaceMember, member_id)
            ).state is WorkspaceMemberState.active
            assert await _event_count(fresh, "workspace.member.reactivate", member_id) == 1


@pytest.mark.anyio
async def test_invitation_revoke_retry_reloads_and_preserves_the_first_revocation(command_sessions):
    async with command_sessions() as db:
        owner, target, workspace, member = await _members(db)
        await terminate_workspace_member(db, owner, workspace.id, member.id)
        invitation, _ = await invite_workspace_member(
            db, owner, workspace.id, target.username, "viewer"
        )
        owner_id, workspace_id, invitation_id = owner.id, workspace.id, invitation.id
        async with command_sessions() as other:
            await revoke_workspace_invitation(
                other, await other.get(User, owner_id), workspace_id, invitation_id
            )
            revoked_at = as_utc((await other.get(type(invitation), invitation_id)).revoked_at)
        assert invitation.revoked_at is None
        await revoke_workspace_invitation(db, owner, workspace_id, invitation_id)
        assert as_utc(invitation.revoked_at) == revoked_at
        assert await _event_count(db, "workspace.invitation.revoke", invitation_id) == 1

        expired, _ = await invite_workspace_member(
            db, owner, workspace_id, target.username, "viewer"
        )
        expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
        await revoke_workspace_invitation(db, owner, workspace_id, expired.id)
        assert expired.revoked_at is None
        assert await _event_count(db, "workspace.invitation.revoke", expired.id) == 0


@pytest.mark.anyio
async def test_governance_retries_preserve_freeze_provenance_and_require_system_authority(
    command_sessions,
):
    async with command_sessions() as db:
        owner, target, workspace, _ = await _members(db)
        workspace_id, owner_id = workspace.id, owner.id
        await recover_workspace_governance(db, owner, workspace_id)
        assert await _event_count(db, "admin.workspace.recover", workspace_id) == 0
        await suspend_workspace_governance(db, owner, workspace_id)
        suspended_at = as_utc(workspace.governance_suspended_at)
        await suspend_workspace_governance(db, owner, workspace_id)
        assert as_utc(workspace.governance_suspended_at) == suspended_at
        assert workspace.governance_suspended_by == owner_id
        assert await _event_count(db, "admin.workspace.suspend", workspace_id) == 1
        with pytest.raises(ResourceNotFound):
            await suspend_workspace_governance(db, target, workspace_id)
        await db.rollback()
        owner = await db.get(User, owner_id)
        await recover_workspace_governance(db, owner, workspace_id)
        await recover_workspace_governance(db, owner, workspace_id)
        assert await _event_count(db, "admin.workspace.recover", workspace_id) == 1
