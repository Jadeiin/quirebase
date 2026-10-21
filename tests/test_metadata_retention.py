"""Expired credentials and terminal history retire without reviving or revoking authority."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, update

from quirebase.accounts import list_user_sessions, purge_expired_account_records
from quirebase.accounts.throttling import THROTTLE_WINDOW
from quirebase.audit import purge_audit_events
from quirebase.core.crypto import token_hash
from quirebase.core.errors import ResourceNotFound
from quirebase.core.persistence import delete_page
from quirebase.models import (
    ApiToken,
    AuditEvent,
    Invitation,
    LoginSession,
    LoginThrottle,
    Project,
    ProjectParticipant,
    User,
    WorkspaceMember,
    WorkspaceRole,
)
from quirebase.workspaces import (
    accept_workspace_invitation_by_id,
    get_received_workspace_invitation,
    invite_workspace_member,
    leave_workspace,
    provision_initial_workspace,
    purge_workspace_history,
)

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


async def test_account_retirement_is_bounded_and_uses_actual_terminal_time(persistence_db):
    db = persistence_db
    now = datetime.now(UTC)
    before = now - timedelta(days=30)
    old = before - timedelta(days=1)
    recent = now - timedelta(days=1)
    future = now + timedelta(days=365)
    user = User(username="retention-user", password_hash="unused")
    db.add(user)
    await db.flush()
    db.add_all([
        LoginSession(token_hash=token_hash(f"session-{i}"), user_id=user.id, expires_at=expiry)
        for i, expiry in enumerate((old, now, future))
    ])
    db.add_all([
        LoginThrottle(identity_hash=token_hash(f"throttle-{i}"), window_started_at=started)
        for i, started in enumerate((old, now - THROTTLE_WINDOW, now))
    ])
    db.add_all([
        ApiToken(
            name=name,
            token_hash=token_hash(name),
            user_id=user.id,
            expires_at=expiry,
            revoked_at=revoked,
        )
        for name, expiry, revoked in (
            ("old-revoked", future, old),
            ("old-expired", before, None),
            ("recent-revocation", old, recent),
            ("recent-expiry", recent, None),
            ("active", future, None),
        )
    ])
    db.add_all([
        Invitation(
            username=name,
            token_hash=token_hash(name),
            created_by=user.id,
            expires_at=expiry,
            accepted_at=accepted,
            revoked_at=revoked,
        )
        for name, expiry, accepted, revoked in (
            ("accepted-old", future, old, None),
            ("revoked-old", future, None, old),
            ("expired-old", before, None, None),
            ("accepted-recent", future, recent, None),
            ("revoked-recent", old, None, recent),
            ("expired-recent", recent, None, None),
            ("pending", future, None, None),
        )
    ])
    await db.commit()

    assert len(await list_user_sessions(db, user)) == 1
    assert await purge_expired_account_records(db, now=now, terminal_before=before, limit=2) == {
        "login_sessions": 2,
        "login_throttles": 2,
        "api_tokens": 2,
        "invitations": 2,
    }
    # The owner operation does not commit independently of its caller.
    await db.rollback()
    assert await db.scalar(select(func.count()).select_from(LoginSession)) == 3
    assert await purge_expired_account_records(db, now=now, terminal_before=before, limit=2) == {
        "login_sessions": 2,
        "login_throttles": 2,
        "api_tokens": 2,
        "invitations": 2,
    }
    assert await purge_expired_account_records(db, now=now, terminal_before=before, limit=2) == {
        "login_sessions": 0,
        "login_throttles": 0,
        "api_tokens": 0,
        "invitations": 1,
    }
    assert set(await db.scalars(select(ApiToken.name))) == {
        "recent-revocation",
        "recent-expiry",
        "active",
    }
    assert set(await db.scalars(select(Invitation.username))) == {
        "accepted-recent",
        "revoked-recent",
        "expired-recent",
        "pending",
    }
    assert await db.scalar(select(func.count()).select_from(LoginThrottle)) == 1


async def test_invitation_receipt_window_preserves_accept_recovery_without_restoring_membership(
    persistence_db,
):
    db = persistence_db
    owner = User(username="receipt-owner", password_hash="unused")
    recipient = User(username="receipt-recipient", password_hash="unused")
    db.add_all([owner, recipient])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    await db.commit()
    invitation, _ = await invite_workspace_member(
        db, owner, workspace.id, recipient.username, "viewer"
    )
    invitation_id, workspace_id, recipient_id = invitation.id, workspace.id, recipient.id
    member = await accept_workspace_invitation_by_id(db, recipient, invitation_id)
    member_id = member.id
    before = datetime.now(UTC) - timedelta(days=30)

    assert await purge_workspace_history(db, before=before) == {
        "workspace_invitations": 0,
        "workspace_members": 0,
    }
    assert (
        await get_received_workspace_invitation(db, recipient, invitation_id)
    ).state == "accepted"
    invitation.accepted_at = before
    await db.commit()
    assert await purge_workspace_history(db, before=before) == {
        "workspace_invitations": 1,
        "workspace_members": 0,
    }
    await db.commit()
    with pytest.raises(ResourceNotFound):
        await get_received_workspace_invitation(db, recipient, invitation_id)
    with pytest.raises(ResourceNotFound):
        await accept_workspace_invitation_by_id(db, recipient, invitation_id)
    assert (await db.get(WorkspaceMember, member_id)).terminated_at is None
    assert (
        await db.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == recipient_id,
            )
        )
        == 1
    )


async def test_retired_membership_does_not_let_an_old_leave_end_a_new_generation(persistence_db):
    db = persistence_db
    owner = User(username="generation-owner", password_hash="unused")
    recipient = User(username="generation-recipient", password_hash="unused")
    db.add_all([owner, recipient])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    await db.commit()
    first, _ = await invite_workspace_member(db, owner, workspace.id, recipient.username, "viewer")
    previous = await accept_workspace_invitation_by_id(db, recipient, first.id)
    workspace_id, previous_id = workspace.id, previous.id
    await leave_workspace(db, recipient, workspace_id, previous_id)
    before = datetime.now(UTC) - timedelta(days=30)
    previous.terminated_at = before
    await db.commit()
    second, _ = await invite_workspace_member(db, owner, workspace_id, recipient.username, "viewer")
    current = await accept_workspace_invitation_by_id(db, recipient, second.id)
    project = Project(workspace_id=workspace_id, name="Current project", created_by=owner.id)
    db.add(project)
    await db.flush()
    participation = ProjectParticipant(
        workspace_id=workspace_id,
        project_id=project.id,
        workspace_member_id=current.id,
        user_id=recipient.id,
    )
    db.add(participation)
    await db.commit()
    current_id, participation_id = current.id, participation.id
    assert await purge_workspace_history(db, before=before) == {
        "workspace_invitations": 0,
        "workspace_members": 1,
    }
    await db.commit()
    assert (
        await db.scalar(select(WorkspaceMember.id).where(WorkspaceMember.id == previous_id)) is None
    )
    with pytest.raises(ResourceNotFound):
        await leave_workspace(db, recipient, workspace_id, previous_id)
    assert (await db.get(WorkspaceMember, current_id)).terminated_at is None
    assert await db.get(ProjectParticipant, participation_id) is not None
    assert (await db.get(WorkspaceMember, current_id)).role is WorkspaceRole.viewer


async def test_audit_retirement_pages_at_500_and_keeps_recent_events(persistence_db):
    db = persistence_db
    now = datetime.now(UTC)
    before = now - timedelta(days=90)
    db.add_all([
        AuditEvent(action="old.event", target_type="test", created_at=before) for _ in range(501)
    ])
    db.add(AuditEvent(action="recent.event", target_type="test", created_at=now))
    await db.commit()
    assert await purge_audit_events(db, before=before) == 500
    assert await purge_audit_events(db, before=before) == 1
    assert await purge_audit_events(db, before=before) == 0
    assert list(await db.scalars(select(AuditEvent.action))) == ["recent.event"]


async def test_delete_page_requires_a_bound_and_a_predicate(persistence_db):
    with pytest.raises(ValueError, match="positive"):
        await delete_page(
            persistence_db, delete(LoginSession).where(LoginSession.id.is_not(None)), limit=0
        )
    with pytest.raises(ValueError, match="predicate"):
        await delete_page(persistence_db, delete(LoginSession))


async def test_throttle_purge_rechecks_a_window_refreshed_while_delete_waits(postgres_race):
    now = datetime.now(UTC)
    identity = token_hash("refreshed-retention-window")
    async with postgres_race.session("seed") as db:
        db.add(
            LoginThrottle(
                identity_hash=identity,
                window_started_at=now - THROTTLE_WINDOW - timedelta(seconds=1),
            )
        )
        await db.commit()

    async def purge():
        async with postgres_race.session("purger") as db:
            result = await purge_expired_account_records(
                db, now=now, terminal_before=now - timedelta(days=30)
            )
            await db.commit()
            return result

    async with postgres_race.session("refresh") as db:
        await db.scalar(
            select(LoginThrottle).where(LoginThrottle.identity_hash == identity).with_for_update()
        )
        postgres_race.start("purger", purge())
        await postgres_race.wait_blocked("purger", "refresh")
        await db.execute(
            update(LoginThrottle)
            .where(LoginThrottle.identity_hash == identity)
            .values(window_started_at=now, failures=1)
        )
        await db.commit()
        assert (await postgres_race.join("purger"))["login_throttles"] == 0
        row = await db.scalar(
            select(LoginThrottle)
            .where(LoginThrottle.identity_hash == identity)
            .execution_options(populate_existing=True)
        )
        assert row is not None and row.window_started_at == now and row.failures == 1
