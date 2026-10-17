from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from quirebase.accounts import (
    InvitationConflict,
    accept_invitation,
    authentication,
    create_invitation,
    get_valid_invitation,
    list_invitations,
    reissue_invitation,
    revoke_invitation,
)
from quirebase.core.crypto import hash_password, token_hash
from quirebase.core.errors import ResourceNotFound
from quirebase.models import AuditEvent, Invitation, User, WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.anyio
PASSWORD = "invitation-password-123"


async def _admin(db):
    admin = User(username="invitation-admin", password_hash="unused", role="administrator")
    db.add(admin)
    await db.commit()
    return admin


async def test_reissue_preserves_history_invalidates_old_link_and_records_provenance(
    persistence_db,
):
    db = persistence_db
    admin = await _admin(db)
    admin_id = admin.id
    previous, old_token = await create_invitation(db, admin, " invitee ", "administrator")
    previous_id = previous.id
    previous_hash = previous.token_hash
    replacement, new_token = await reissue_invitation(db, admin, previous.id)
    assert replacement.id != previous_id
    assert replacement.username == "invitee"
    assert replacement.role == "administrator"
    assert new_token != old_token
    assert replacement.token_hash == token_hash(new_token)
    assert previous.token_hash == previous_hash
    assert previous.revoked_at is not None
    assert await get_valid_invitation(db, old_token) is None
    with pytest.raises(ResourceNotFound):
        await accept_invitation(db, old_token, PASSWORD)
    await db.rollback()
    with pytest.raises(ResourceNotFound):
        await reissue_invitation(db, admin, previous_id)
    await db.rollback()
    user = await accept_invitation(db, new_token, PASSWORD)
    assert user.username == "invitee"
    assert user.role == "administrator"
    assert await db.scalar(
        select(WorkspaceMember.id).where(
            WorkspaceMember.user_id == user.id, WorkspaceMember.role == WorkspaceRole.owner
        )
    )
    assert await get_valid_invitation(db, new_token) is None
    events = list(
        await db.scalars(
            select(AuditEvent)
            .where(AuditEvent.action.like("invitation.%"))
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
    )
    assert [event.action for event in events] == [
        "invitation.create",
        "invitation.revoke",
        "invitation.create",
        "invitation.reissue",
        "invitation.accept",
    ]
    assert all(event.actor_id == admin_id for event in events[:-1])
    assert events[3].target_id == str(previous_id)
    assert events[3].detail["replacement_invitation_id"] == str(replacement.id)
    assert events[-1].actor_id == user.id
    assert events[-1].detail == {"invitation_id": str(replacement.id)}
    assert all(
        old_token not in str(event.detail) and new_token not in str(event.detail)
        for event in events
    )


async def test_expired_invitation_can_be_replaced_without_losing_history(persistence_db):
    db = persistence_db
    admin = await _admin(db)
    expired, old_token = await create_invitation(db, admin, "expired-invitee")
    expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    expired_id = expired.id
    replacement, token = await create_invitation(db, admin, "expired-invitee")
    assert expired.revoked_at is not None
    assert replacement.id != expired_id
    assert await get_valid_invitation(db, old_token) is None
    assert (await get_valid_invitation(db, token)).id == replacement.id
    with pytest.raises(InvitationConflict):
        await create_invitation(db, admin, "expired-invitee")
    assert await db.scalar(select(func.count()).select_from(Invitation)) == 2


async def test_revoke_retry_reloads_stale_state_and_preserves_first_audit(persistence_sessions):
    async with persistence_sessions() as db:
        admin = await _admin(db)
        invitation, token = await create_invitation(db, admin, "revoked-invitee")
        admin_id, invitation_id = admin.id, invitation.id
        async with persistence_sessions() as other:
            await revoke_invitation(other, await other.get(User, admin_id), invitation_id)
            first_revocation = (await other.get(Invitation, invitation_id)).revoked_at
        assert invitation.revoked_at is None
        await revoke_invitation(db, admin, invitation_id)
        assert invitation.revoked_at == first_revocation
        assert await get_valid_invitation(db, token) is None
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "invitation.revoke")
            )
            == 1
        )
        replacement, _ = await create_invitation(db, admin, "revoked-invitee")
        assert replacement.id != invitation_id


async def test_invitation_states_and_pagination_exclude_expired_from_pending(persistence_db):
    db = persistence_db
    admin = await _admin(db)
    accepted, token = await create_invitation(db, admin, "accepted-invitee")
    await accept_invitation(db, token, PASSWORD)
    revoked, _ = await create_invitation(db, admin, "revoked-invitee")
    await revoke_invitation(db, admin, revoked.id)
    expired, _ = await create_invitation(db, admin, "expired-invitee")
    expired.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()
    pending, _ = await create_invitation(db, admin, "pending-invitee")
    expected = {
        "accepted": accepted.id,
        "revoked": revoked.id,
        "expired": expired.id,
        "pending": pending.id,
    }
    for state, identity in expected.items():
        rows, total = await list_invitations(db, admin, state=state)
        assert total == 1
        assert [row.id for row in rows] == [identity]
    rows, total = await list_invitations(db, admin, limit=2, offset=1)
    assert total == 4
    assert [row.id for row in rows] == [expired.id, revoked.id]
    rows, total = await list_invitations(db, admin, offset=100)
    assert rows == [] and total == 4


async def test_partial_unique_index_allows_history_but_only_one_pending_link(persistence_db):
    db = persistence_db
    admin = await _admin(db)
    invitation, _ = await create_invitation(db, admin, "unique-invitee")
    duplicate = Invitation(
        username=invitation.username,
        token_hash=token_hash("duplicate"),
        role="member",
        created_by=admin.id,
        expires_at=invitation.expires_at,
    )
    nested = await db.begin_nested()
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        await db.flush()
    await nested.rollback()
    await revoke_invitation(db, admin, invitation.id)
    replacement, _ = await create_invitation(db, admin, "unique-invitee")
    assert replacement.id != invitation.id


@pytest.mark.parametrize("operation", ["revoke", "reissue"])
async def test_accept_rechecks_link_after_password_hashing(
    persistence_sessions, monkeypatch, operation
):
    async with persistence_sessions() as db:
        admin = await _admin(db)
        invitation, token = await create_invitation(db, admin, "racing-invitee")
        admin_id, invitation_id = admin.id, invitation.id
    hashing_started, finish_hashing = asyncio.Event(), asyncio.Event()
    encoded = hash_password(PASSWORD)

    async def delayed_hash(_password):
        hashing_started.set()
        await finish_hashing.wait()
        return encoded

    monkeypatch.setattr(authentication, "hash_password_async", delayed_hash)

    async def accept():
        async with persistence_sessions() as db:
            with pytest.raises(ResourceNotFound):
                await accept_invitation(db, token, PASSWORD)

    task = asyncio.create_task(accept())
    try:
        await asyncio.wait_for(hashing_started.wait(), timeout=5)
        async with persistence_sessions() as db:
            admin = await db.get(User, admin_id)
            if operation == "revoke":
                await revoke_invitation(db, admin, invitation_id)
            else:
                await reissue_invitation(db, admin, invitation_id)
    finally:
        finish_hashing.set()
        await asyncio.wait_for(task, timeout=5)
    async with persistence_sessions() as db:
        assert await db.scalar(select(User.id).where(User.username == "racing-invitee")) is None
        invitation = await db.get(Invitation, invitation_id)
        assert invitation.accepted_at is None and invitation.revoked_at is not None


async def test_concurrent_reissues_create_exactly_one_replacement(persistence_sessions):
    async with persistence_sessions() as db:
        admin = await _admin(db)
        invitation, _ = await create_invitation(db, admin, "reissue-race")
        admin_id, invitation_id = admin.id, invitation.id

    async def reissue():
        async with persistence_sessions() as db:
            try:
                return await reissue_invitation(db, await db.get(User, admin_id), invitation_id)
            except ResourceNotFound:
                return None

    results = await asyncio.wait_for(asyncio.gather(reissue(), reissue()), timeout=5)
    assert sum(result is not None for result in results) == 1
    async with persistence_sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Invitation)) == 2
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "invitation.reissue")
            )
            == 1
        )


async def test_concurrent_accepts_provision_exactly_one_user(persistence_sessions, monkeypatch):
    async with persistence_sessions() as db:
        admin = await _admin(db)
        _, token = await create_invitation(db, admin, "accept-race")
    monkeypatch.setattr(
        authentication, "hash_password_async", AsyncMock(return_value=hash_password(PASSWORD))
    )

    async def accept():
        async with persistence_sessions() as db:
            try:
                return await accept_invitation(db, token, PASSWORD)
            except ResourceNotFound:
                return None

    results = await asyncio.wait_for(asyncio.gather(accept(), accept()), timeout=5)
    assert sum(result is not None for result in results) == 1
    async with persistence_sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WorkspaceMember)) == 1
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "invitation.accept")
            )
            == 1
        )
