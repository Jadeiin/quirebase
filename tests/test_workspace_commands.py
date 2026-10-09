"""State-setting retries must retain authority checks and record only actual transitions."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from quirebase.access import resolve_workspace_context
from quirebase.core.errors import PermissionDenied, ResourceNotFound, ValidationFailure
from quirebase.models import (
    AuditEvent,
    Item,
    Project,
    ProjectParticipant,
    ProjectParticipation,
    ProjectState,
    User,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
)
from quirebase.projects import create_project, open_project_workspace, set_project_state
from quirebase.workspaces import (
    freeze_workspace_governance,
    invite_workspace_member,
    provision_initial_workspace,
    reactivate_workspace_member,
    read_workspace_items_break_glass,
    revoke_workspace_invitation,
    set_workspace_member_role,
    suspend_workspace_member,
    terminate_workspace_member,
    transfer_workspace_ownership,
    unfreeze_workspace_governance,
)


@pytest.fixture(
    params=[
        pytest.param("async_session_factory", id="sqlite"),
        pytest.param("postgres_sessions", id="postgres", marks=pytest.mark.shared_postgres),
    ]
)
def command_sessions(request):
    return request.getfixturevalue(request.param)


@pytest.mark.anyio
async def test_project_defaults_select_open_without_workspace_wide_participation(command_sessions):
    async with command_sessions() as db:
        owner, target, workspace, _member = await _members(db)
        project = await create_project(db, owner, workspace.id, "Open by default")
        assert project.participation is ProjectParticipation.open
        assert list(await db.scalars(select(ProjectParticipant.user_id))) == [owner.id]
        other_context = await resolve_workspace_context(db, target, workspace.id)
        visible = await open_project_workspace(db, other_context, project.id)
        assert not visible.is_participating
        direct = Project(workspace_id=workspace.id, created_by=owner.id, name="ORM default")
        db.add(direct)
        await db.flush()
        assert direct.participation is ProjectParticipation.open


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
        .where(AuditEvent.action == action, AuditEvent.target_id == str(target_id))
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
        suspended_at = member.suspended_at
        await suspend_workspace_member(db, owner, workspace_id, member_id)
        assert member.suspended_at == suspended_at
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
async def test_ownership_transfer_audits_the_authorizing_role_and_reloads_next_command(
    command_sessions,
):
    async with command_sessions() as db:
        owner, _, workspace, target = await _members(db)
        owner_id, workspace_id, target_id = owner.id, workspace.id, target.id
        context = await resolve_workspace_context(db, owner, workspace_id)
        await transfer_workspace_ownership(db, owner, workspace_id, target_id)
        assert context.membership.role is WorkspaceRole.admin
        assert context.role is WorkspaceRole.owner
        event = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "workspace.ownership.transfer",
                AuditEvent.target_id == str(workspace_id),
            )
        )
        assert event.actor_id == owner_id
        assert event.authorization_role == "owner"
        assert target.role is WorkspaceRole.owner
        fresh = await resolve_workspace_context(db, owner, workspace_id)
        assert fresh.role is WorkspaceRole.admin
        previous_owner = fresh.membership.id
        with pytest.raises(PermissionDenied):
            await transfer_workspace_ownership(db, owner, workspace_id, previous_owner)
        await db.rollback()
        assert await _event_count(db, "workspace.ownership.transfer", workspace_id) == 1


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
            revoked_at = (await other.get(type(invitation), invitation_id)).revoked_at
        assert invitation.revoked_at is None
        await revoke_workspace_invitation(db, owner, workspace_id, invitation_id)
        assert invitation.revoked_at == revoked_at
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
        await unfreeze_workspace_governance(db, owner, workspace_id)
        assert await _event_count(db, "admin.workspace.unfreeze", workspace_id) == 0
        await freeze_workspace_governance(db, owner, workspace_id)
        frozen_at = workspace.governance_frozen_at
        await freeze_workspace_governance(db, owner, workspace_id)
        assert workspace.governance_frozen_at == frozen_at
        assert workspace.governance_frozen_by == owner_id
        assert await _event_count(db, "admin.workspace.freeze", workspace_id) == 1
        with pytest.raises(ResourceNotFound):
            await freeze_workspace_governance(db, target, workspace_id)
        await db.rollback()
        owner = await db.get(User, owner_id)
        await unfreeze_workspace_governance(db, owner, workspace_id)
        await unfreeze_workspace_governance(db, owner, workspace_id)
        assert await _event_count(db, "admin.workspace.unfreeze", workspace_id) == 1


@pytest.mark.anyio
async def test_break_glass_inspection_is_bounded_and_audits_only_successful_reads(command_sessions):
    async with command_sessions() as db:
        owner, _, workspace, _ = await _members(db)
        admin = User(username="inspection-admin", password_hash="unused", role="administrator")
        db.add(admin)
        db.add_all([
            Item(workspace_id=workspace.id, title=f"Item {index}", created_by=owner.id)
            for index in range(101)
        ])
        await db.commit()
        admin_id, workspace_id = admin.id, workspace.id
        reason = "Investigate reported data loss"
        items = await read_workspace_items_break_glass(db, admin, workspace_id, reason)
        assert len(items) == 100
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "admin.workspace.break_glass.read")
        )
        assert event.detail["result_count"] == 100
        assert (
            await db.scalar(
                select(WorkspaceMember.id).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == admin_id,
                )
            )
            is None
        )
        for limit in (0, 101):
            admin = await db.get(User, admin_id)
            with pytest.raises(ValidationFailure, match="between 1 and 100"):
                await read_workspace_items_break_glass(db, admin, workspace_id, reason, limit=limit)
            await db.rollback()
        assert await _event_count(db, "admin.workspace.break_glass.read", workspace_id) == 1
