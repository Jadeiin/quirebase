from __future__ import annotations

import pytest
from sqlalchemy import select

from quirebase.accounts import (
    authenticate_user,
    change_user_role,
    create_login_session,
    create_user_admin,
    list_users_paginated,
    reset_user_password,
    revoke_user_sessions,
    update_user_status,
)
from quirebase.core.crypto import hash_password
from quirebase.core.errors import (
    PermissionDenied,
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.models import AuditEvent, LoginSession, User


async def create_test_admin(db, username="admin_tester"):
    admin = User(
        username=username,
        password_hash=hash_password("adminpass123456"),
        role="administrator",
        active=True,
    )
    db.add(admin)
    await db.commit()
    return admin


async def create_test_member(db, username="member_tester"):
    user = User(
        username=username,
        password_hash=hash_password("memberpass123456"),
        role="member",
        active=True,
    )
    db.add(user)
    await db.commit()
    return user


@pytest.mark.anyio
async def test_admin_create_user_and_authenticate(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin1")
    new_user = await create_user_admin(db, admin, "new_member_1", "securepass123456", role="member")
    assert new_user.id is not None
    assert new_user.username == "new_member_1"
    assert new_user.role == "member"
    assert new_user.active is True

    # Check audit event
    event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "admin.user.create", AuditEvent.target_id == new_user.id
        )
    )
    assert event is not None
    assert event.actor_id == admin.id

    # Test authentication with new user
    session, _token = await authenticate_user(db, "127.0.0.1", "new_member_1", "securepass123456")
    assert session.user_id == new_user.id


@pytest.mark.anyio
async def test_non_admin_cannot_create_user(async_db):
    db = async_db
    member = await create_test_member(db, "member1")
    with pytest.raises(ResourceUnavailable, match="administrator required"):
        await create_user_admin(db, member, "sneaky_user", "password123456")


@pytest.mark.anyio
async def test_admin_create_user_duplicate_username_fails(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin2")
    await create_user_admin(db, admin, "unique_user", "password123456")
    with pytest.raises(ValidationFailure, match="already taken"):
        await create_user_admin(db, admin, "unique_user", "password123456")


@pytest.mark.anyio
async def test_admin_toggle_user_status_and_session_revocation(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin3")
    user = await create_user_admin(db, admin, "target_user", "password123456")

    # Create active sessions
    _session1, _ = await create_login_session(db, user)
    _session2, _ = await create_login_session(db, user)
    await db.commit()
    assert (
        len(
            list(
                (
                    await db.scalars(select(LoginSession).where(LoginSession.user_id == user.id))
                ).all()
            )
        )
        == 2
    )

    # Deactivate user
    await update_user_status(db, admin, user.id, active=False)
    assert user.active is False

    # Sessions must be wiped
    active_sessions = list(
        (await db.scalars(select(LoginSession).where(LoginSession.user_id == user.id))).all()
    )
    assert len(active_sessions) == 0

    # Self-deactivation by admin must be rejected
    with pytest.raises(PermissionDenied, match="cannot deactivate their own account"):
        await update_user_status(db, admin, admin.id, active=False)


@pytest.mark.anyio
async def test_admin_change_user_role(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin4")
    user = await create_user_admin(db, admin, "role_target", "password123456", role="member")
    assert user.role == "member"

    # Promote to admin
    await change_user_role(db, admin, user.id, new_role="administrator")
    assert user.role == "administrator"

    # Self-demotion must be blocked
    with pytest.raises(PermissionDenied, match="cannot demote their own account"):
        await change_user_role(db, admin, admin.id, new_role="member")


@pytest.mark.anyio
async def test_admin_reset_password(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin5")
    user = await create_user_admin(db, admin, "pw_target", "oldpass123456")
    await create_login_session(db, user)
    await db.commit()

    await reset_user_password(db, admin, user.id, "brand_new_pass_456")

    # Old session is revoked
    assert (
        len(
            list(
                (
                    await db.scalars(select(LoginSession).where(LoginSession.user_id == user.id))
                ).all()
            )
        )
        == 0
    )

    # Can authenticate with new password
    session, _ = await authenticate_user(db, "127.0.0.1", "pw_target", "brand_new_pass_456")
    assert session.user_id == user.id


@pytest.mark.anyio
async def test_admin_revoke_sessions(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin6")
    user = await create_user_admin(db, admin, "sess_target", "pass123456789")
    await create_login_session(db, user)
    await create_login_session(db, user)
    await db.commit()

    revoked = await revoke_user_sessions(db, admin, user.id)
    assert revoked == 2
    assert (
        len(
            list(
                (
                    await db.scalars(select(LoginSession).where(LoginSession.user_id == user.id))
                ).all()
            )
        )
        == 0
    )


@pytest.mark.anyio
async def test_list_users_paginated_and_filtered(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin7")
    await create_user_admin(db, admin, "alpha_member", "pass123456789", role="member")
    await create_user_admin(db, admin, "beta_admin", "pass123456789", role="administrator")
    u3 = await create_user_admin(db, admin, "gamma_disabled", "pass123456789", role="member")
    await update_user_status(db, admin, u3.id, active=False)

    users, total = await list_users_paginated(db, admin, search="alpha")
    assert total == 1
    assert users[0].username == "alpha_member"

    users, total = await list_users_paginated(db, admin, role="administrator")
    assert any(u.username == "beta_admin" for u in users)

    users, total = await list_users_paginated(db, admin, active=False)
    assert total == 1
    assert users[0].username == "gamma_disabled"
