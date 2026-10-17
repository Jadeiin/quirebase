"""Account containment and explicit ownership recovery preserve structural governance."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from quirebase.access import ResourceAction, require_workspace_action, resolve_workspace_context
from quirebase.accounts import (
    accept_invitation,
    create_api_token,
    create_invitation,
    create_user_admin,
    update_user_status,
    verify_api_token,
)
from quirebase.core.crypto import token_hash
from quirebase.core.errors import (
    ResourceNotFound,
    ValidationFailure,
    VersionConflict,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
)
from quirebase.models import (
    AuditEvent,
    LoginSession,
    Project,
    ProjectParticipant,
    ProjectParticipation,
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.workspaces import (
    check_workspace_integrity,
    provision_initial_workspace,
    reassign_workspace_owner,
    transfer_workspace_ownership,
    workspace_owner_ids,
    workspace_owners,
)


async def _setup(db):
    admin = User(username="governor", password_hash="unused", role="administrator")
    owner = User(username="owner", password_hash="unused")
    receiver = User(username="successor", password_hash="unused")
    db.add_all([admin, owner, receiver])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    await db.commit()
    return admin, owner, receiver, workspace


@pytest.mark.anyio
@pytest.mark.parametrize("provisioning", ["admin", "invitation"])
async def test_newly_provisioned_owner_can_be_disabled(persistence_db, provisioning):
    db = persistence_db
    admin, _, _, _ = await _setup(db)
    if provisioning == "admin":
        target = await create_user_admin(db, admin, "new-user", "password-123456")
    else:
        _, raw = await create_invitation(db, admin, "new-user")
        target = await accept_invitation(db, raw, "password-123456")
    workspace_id = await db.scalar(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == target.id)
    )
    session = LoginSession(
        user_id=target.id,
        token_hash=token_hash("owner-session"),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(session)
    await db.commit()
    session_id = session.id
    token = await create_api_token(db, target, "integration", expires_in_days=1)
    await update_user_status(db, admin, target.id, False)
    assert not target.active
    assert await db.get(LoginSession, session_id) is None
    assert await verify_api_token(db, token.raw_token) is None
    assert await workspace_owner_ids(db, {workspace_id}) == {workspace_id: target.id}
    assert not (await workspace_owners(db, {workspace_id}))[workspace_id].active
    assert await check_workspace_integrity(db) == []
    with pytest.raises(WorkspaceMembershipRequired):
        await resolve_workspace_context(db, target, workspace_id)
    await update_user_status(db, admin, target.id, True)
    assert await verify_api_token(db, token.raw_token) is not None
    assert (await resolve_workspace_context(db, target, workspace_id)).role is WorkspaceRole.owner
    assert await db.get(LoginSession, session_id) is None


@pytest.mark.anyio
@pytest.mark.parametrize("membership", ["absent", "active", "suspended", "terminated"])
async def test_reassignment_preserves_membership_generations_and_audits_access(
    persistence_db, membership
):
    db = persistence_db
    admin, owner, receiver, workspace = await _setup(db)
    old_membership = None
    project = Project(
        workspace_id=workspace.id,
        created_by=owner.id,
        name="Managed research",
        participation=ProjectParticipation.managed,
    )
    db.add(project)
    await db.flush()
    if membership != "absent":
        old_membership = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=receiver.id,
            role=WorkspaceRole.viewer,
            state=WorkspaceMemberState.suspended
            if membership == "suspended"
            else WorkspaceMemberState.active,
            suspended_at=datetime.now(UTC) if membership == "suspended" else None,
            terminated_at=datetime.now(UTC) if membership == "terminated" else None,
        )
        db.add(old_membership)
        await db.flush()
        if membership != "terminated":
            db.add(
                ProjectParticipant(
                    workspace_id=workspace.id,
                    workspace_member_id=old_membership.id,
                    user_id=receiver.id,
                    project_id=project.id,
                )
            )
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        user_id=receiver.id,
        role=WorkspaceRole.viewer,
        token_hash=token_hash("pending-workspace-invitation"),
        invited_by=owner.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(invitation)
    await db.commit()
    await update_user_status(db, admin, owner.id, False)
    await reassign_workspace_owner(
        db, admin, workspace.id, receiver.id, owner.id, "  Offboarding the previous owner  "
    )
    current = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == receiver.id,
            WorkspaceMember.terminated_at.is_(None),
        )
    )
    assert current.role is WorkspaceRole.owner
    assert current.state is WorkspaceMemberState.active and current.suspended_at is None
    if membership in {"absent", "terminated"}:
        assert old_membership is None or current.id != old_membership.id
        assert await db.scalar(select(ProjectParticipant.id)) is None
    else:
        assert current.id == old_membership.id
        assert await db.scalar(select(ProjectParticipant.workspace_member_id)) == current.id
    if membership != "active":
        assert invitation.revoked_at is not None
    previous = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == owner.id
        )
    )
    assert previous.role is WorkspaceRole.admin and not owner.active
    assert (
        await db.scalar(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == admin.id
            )
        )
        is None
    )
    assert await check_workspace_integrity(db) == []
    event = await db.scalar(
        select(AuditEvent).where(AuditEvent.action == "admin.workspace.owner_reassign")
    )
    assert event.actor_id == admin.id and event.workspace_id == workspace.id
    assert event.authorization_resource_action == "workspace_governance.reassign_owner"
    assert event.detail == {
        "previous_owner_id": str(owner.id),
        "owner_id": str(receiver.id),
        "membership_id": str(current.id),
        "membership_effect": {
            "absent": "admitted",
            "terminated": "admitted",
            "active": "promoted",
            "suspended": "reactivated",
        }[membership],
        "reason": "Offboarding the previous owner",
    }
    with pytest.raises(WorkspaceMembershipRequired):
        await resolve_workspace_context(db, admin, workspace.id)
    await update_user_status(db, admin, owner.id, True)
    assert (await resolve_workspace_context(db, owner, workspace.id)).role is WorkspaceRole.admin


@pytest.mark.anyio
@pytest.mark.parametrize("state", [WorkspaceState.active, WorkspaceState.archived])
async def test_reassignment_noop_conflict_lifecycle_and_other_member_authority(
    persistence_db, state
):
    db = persistence_db
    admin, owner, receiver, workspace = await _setup(db)
    workspace.state = state
    workspace.archived_at = datetime.now(UTC) if state is WorkspaceState.archived else None
    editor = User(username="editor", password_hash="unused")
    db.add(editor)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=editor.id, role=WorkspaceRole.editor))
    await db.commit()
    workspace_id, owner_id, receiver_id, admin_id = workspace.id, owner.id, receiver.id, admin.id
    await reassign_workspace_owner(
        db, admin, workspace_id, owner_id, owner_id, "Ownership already correct"
    )
    assert (
        await db.scalar(
            select(AuditEvent.id).where(AuditEvent.action == "admin.workspace.owner_reassign")
        )
        is None
    )
    await update_user_status(db, admin, owner_id, False)
    if state is WorkspaceState.active:
        await require_workspace_action(db, editor, workspace_id, ResourceAction.item_create)
    await reassign_workspace_owner(
        db, admin, workspace_id, receiver_id, owner_id, "Restore accountable governance"
    )
    assert workspace.state is state
    with pytest.raises(VersionConflict):
        await reassign_workspace_owner(
            db, admin, workspace_id, admin_id, owner_id, "Stale ownership information"
        )
    await db.rollback()
    admin = await db.get(User, admin_id)
    workspace = await db.get(type(workspace), workspace_id)
    workspace.governance_frozen_at = datetime.now(UTC)
    workspace.governance_frozen_by = admin_id
    await db.commit()
    with pytest.raises(WorkspaceLifecycleError):
        await reassign_workspace_owner(
            db, admin, workspace_id, admin_id, receiver_id, "Explicit freeze still applies"
        )
    await db.rollback()
    assert (
        await db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "admin.workspace.owner_reassign")
        )
        == 1
    )


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", ["inactive", "missing", "unauthorized", "demoted", "reason"])
async def test_reassignment_revalidates_actor_receiver_and_reason(persistence_db, invalid):
    db = persistence_db
    admin, owner, receiver, workspace = await _setup(db)
    workspace_id, owner_id, receiver_id, admin_id = workspace.id, owner.id, receiver.id, admin.id
    if invalid == "inactive":
        receiver.active = False
    if invalid == "demoted":
        # A stale ORM principal cannot retain administrator authority.
        await db.execute(User.__table__.update().where(User.id == admin_id).values(role="member"))
    await db.commit()
    with pytest.raises(
        ResourceNotFound if invalid in {"unauthorized", "demoted"} else ValidationFailure
    ):
        await reassign_workspace_owner(
            db,
            owner if invalid == "unauthorized" else admin,
            workspace_id,
            uuid4() if invalid == "missing" else receiver_id,
            owner_id,
            "           " if invalid == "reason" else "Recover workspace ownership",
        )
    await db.rollback()
    assert await workspace_owner_ids(db, {workspace_id}) == {workspace_id: owner_id}
    assert (
        await db.scalar(
            select(AuditEvent.id).where(AuditEvent.action == "admin.workspace.owner_reassign")
        )
        is None
    )


@pytest.mark.anyio
@pytest.mark.shared_postgres
@pytest.mark.concurrency_case("owner-reassignment")
@pytest.mark.parametrize("first", ["reassign", "transfer"])
async def test_reassignment_serializes_with_ordinary_transfer(
    postgres_sessions, postgres_race, first
):
    async with postgres_sessions() as db:
        admin, owner, receiver, workspace = await _setup(db)
        other = User(username="other-successor", password_hash="unused")
        db.add(other)
        await db.flush()
        membership = WorkspaceMember(
            workspace_id=workspace.id, user_id=receiver.id, role=WorkspaceRole.editor
        )
        db.add(membership)
        await db.commit()
        admin_id, owner_id, receiver_id, other_id, workspace_id, membership_id = (
            admin.id,
            owner.id,
            receiver.id,
            other.id,
            workspace.id,
            membership.id,
        )

    async def change(name):
        from quirebase.core.errors import PermissionDenied

        async with postgres_race.session(name) as db:
            actor = await db.get(User, admin_id if name == "reassign" else owner_id)
            try:
                if name == "reassign":
                    await reassign_workspace_owner(
                        db, actor, workspace_id, other_id, owner_id, "Recover ownership explicitly"
                    )
                else:
                    await transfer_workspace_ownership(db, actor, workspace_id, membership_id)
            except (PermissionDenied, VersionConflict) as error:
                await db.rollback()
                return type(error).__name__
            return "changed"

    async with postgres_race.session("root-holder") as db:
        await db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
        second = "transfer" if first == "reassign" else "reassign"
        postgres_race.start(first, change(first))
        await postgres_race.wait_blocked(first, "root-holder")
        postgres_race.start(second, change(second))
        await postgres_race.wait_blocked(second, first)
        await db.commit()
    assert await postgres_race.join(first) == "changed"
    assert await postgres_race.join(second) == (
        "PermissionDenied" if first == "reassign" else "VersionConflict"
    )
    async with postgres_sessions() as db:
        assert await workspace_owner_ids(db, {workspace_id}) == {
            workspace_id: other_id if first == "reassign" else receiver_id
        }
        assert await check_workspace_integrity(db) == []


@pytest.mark.anyio
@pytest.mark.shared_postgres
@pytest.mark.concurrency_case("owner-reassignment")
async def test_competing_administrative_reassignments_compare_expected_owner(
    postgres_sessions, postgres_race
):
    async with postgres_sessions() as db:
        admin, owner, receiver, workspace = await _setup(db)
        admin_id, owner_id, receiver_id, workspace_id = (
            admin.id,
            owner.id,
            receiver.id,
            workspace.id,
        )

    async def change(name, receiving_id):
        async with postgres_race.session(name) as db:
            actor = await db.get(User, admin_id)
            try:
                await reassign_workspace_owner(
                    db, actor, workspace_id, receiving_id, owner_id, "Recover ownership explicitly"
                )
            except VersionConflict:
                await db.rollback()
                return "conflict"
            return "changed"

    async with postgres_race.session("root-holder") as db:
        await db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
        postgres_race.start("first", change("first", receiver_id))
        await postgres_race.wait_blocked("first", "root-holder")
        postgres_race.start("second", change("second", admin_id))
        await postgres_race.wait_blocked("second", "first")
        await db.commit()
    assert await postgres_race.join("first") == "changed"
    assert await postgres_race.join("second") == "conflict"
    async with postgres_sessions() as db:
        assert await workspace_owner_ids(db, {workspace_id}) == {workspace_id: receiver_id}
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "admin.workspace.owner_reassign")
            )
            == 1
        )


@pytest.mark.anyio
@pytest.mark.shared_postgres
@pytest.mark.concurrency_case("actor-revocation")
@pytest.mark.parametrize("deactivation_first", [False, True])
async def test_reassignment_and_receiver_deactivation_follow_user_root_order(
    postgres_sessions, postgres_race, deactivation_first
):
    async with postgres_sessions() as db:
        admin, owner, receiver, workspace = await _setup(db)
        admin_id, owner_id, receiver_id, workspace_id = (
            admin.id,
            owner.id,
            receiver.id,
            workspace.id,
        )

    async def reassign():
        async with postgres_race.session("reassign") as db:
            actor = await db.get(User, admin_id)
            try:
                await reassign_workspace_owner(
                    db, actor, workspace_id, receiver_id, owner_id, "Recover ownership explicitly"
                )
            except ValidationFailure:
                await db.rollback()
                return "inactive"
            return "changed"

    async def deactivate():
        async with postgres_race.session("deactivate") as db:
            await update_user_status(db, await db.get(User, admin_id), receiver_id, False)

    async with postgres_race.session("holder") as db:
        if deactivation_first:
            await db.scalar(
                select(User).where(User.id == receiver_id).with_for_update(key_share=True)
            )
            postgres_race.start("reassign", reassign())
            await postgres_race.wait_blocked("reassign", "holder")
            await update_user_status(db, await db.get(User, admin_id), receiver_id, False)
        else:
            await db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
            postgres_race.start("reassign", reassign())
            await postgres_race.wait_blocked("reassign", "holder")
            postgres_race.start("deactivate", deactivate())
            await postgres_race.wait_blocked("deactivate", "reassign")
            await db.commit()
    assert await postgres_race.join("reassign") == ("inactive" if deactivation_first else "changed")
    if not deactivation_first:
        await postgres_race.join("deactivate")
    async with postgres_sessions() as db:
        assert not (await db.get(User, receiver_id)).active
        assert await workspace_owner_ids(db, {workspace_id}) == {
            workspace_id: owner_id if deactivation_first else receiver_id
        }
        assert await check_workspace_integrity(db) == []


@pytest.mark.anyio
@pytest.mark.shared_postgres
@pytest.mark.concurrency_case("governance-demotion")
async def test_reassignment_rechecks_administrator_after_user_guard_wait(
    postgres_sessions, postgres_race
):
    from quirebase.accounts import change_user_role

    async with postgres_sessions() as db:
        admin, owner, receiver, workspace = await _setup(db)
        supervisor = User(username="supervisor", password_hash="unused", role="administrator")
        db.add(supervisor)
        await db.commit()
        admin_id, owner_id, receiver_id, workspace_id, supervisor_id = (
            admin.id,
            owner.id,
            receiver.id,
            workspace.id,
            supervisor.id,
        )

    async def change():
        async with postgres_race.session("reassign") as db:
            actor = await db.get(User, admin_id)
            try:
                await reassign_workspace_owner(
                    db, actor, workspace_id, receiver_id, owner_id, "Recover ownership explicitly"
                )
            except ResourceNotFound:
                await db.rollback()
                return "denied"
            return "changed"

    async with postgres_race.session("holder") as db:
        await db.scalar(select(User).where(User.id == admin_id).with_for_update(key_share=True))
        postgres_race.start("reassign", change())
        await postgres_race.wait_blocked("reassign", "holder")
        await change_user_role(db, await db.get(User, supervisor_id), admin_id, "member")
    assert await postgres_race.join("reassign") == "denied"
    async with postgres_sessions() as db:
        assert await workspace_owner_ids(db, {workspace_id}) == {workspace_id: owner_id}
