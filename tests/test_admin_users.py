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


def create_test_admin(db, username="admin_tester"):
    admin = User(
        username=username,
        password_hash=hash_password("adminpass123456"),
        role="administrator",
        active=True,
    )
    db.add(admin)
    db.commit()
    return admin


def create_test_member(db, username="member_tester"):
    user = User(
        username=username,
        password_hash=hash_password("memberpass123456"),
        role="member",
        active=True,
    )
    db.add(user)
    db.commit()
    return user


def test_admin_create_user_and_authenticate(db):
    admin = create_test_admin(db, "admin1")
    new_user = create_user_admin(db, admin, "new_member_1", "securepass123456", role="member")
    assert new_user.id is not None
    assert new_user.username == "new_member_1"
    assert new_user.role == "member"
    assert new_user.active is True

    # Check audit event
    event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "admin.user.create", AuditEvent.target_id == new_user.id
        )
    )
    assert event is not None
    assert event.actor_id == admin.id

    # Test authentication with new user
    session, _token = authenticate_user(db, "127.0.0.1", "new_member_1", "securepass123456")
    assert session.user_id == new_user.id


def test_non_admin_cannot_create_user(db):
    member = create_test_member(db, "member1")
    with pytest.raises(ResourceUnavailable, match="administrator required"):
        create_user_admin(db, member, "sneaky_user", "password123456")


def test_admin_create_user_duplicate_username_fails(db):
    admin = create_test_admin(db, "admin2")
    create_user_admin(db, admin, "unique_user", "password123456")
    with pytest.raises(ValidationFailure, match="already taken"):
        create_user_admin(db, admin, "unique_user", "password123456")


def test_admin_toggle_user_status_and_session_revocation(db):
    admin = create_test_admin(db, "admin3")
    user = create_user_admin(db, admin, "target_user", "password123456")

    # Create active sessions
    _session1, _ = create_login_session(db, user)
    _session2, _ = create_login_session(db, user)
    db.commit()
    assert (
        len(list(db.scalars(select(LoginSession).where(LoginSession.user_id == user.id)).all()))
        == 2
    )

    # Deactivate user
    update_user_status(db, admin, user.id, active=False)
    assert user.active is False

    # Sessions must be wiped
    active_sessions = list(
        db.scalars(select(LoginSession).where(LoginSession.user_id == user.id)).all()
    )
    assert len(active_sessions) == 0

    # Self-deactivation by admin must be rejected
    with pytest.raises(PermissionDenied, match="cannot deactivate their own account"):
        update_user_status(db, admin, admin.id, active=False)


def test_admin_change_user_role(db):
    admin = create_test_admin(db, "admin4")
    user = create_user_admin(db, admin, "role_target", "password123456", role="member")
    assert user.role == "member"

    # Promote to admin
    change_user_role(db, admin, user.id, new_role="administrator")
    assert user.role == "administrator"

    # Self-demotion must be blocked
    with pytest.raises(PermissionDenied, match="cannot demote their own account"):
        change_user_role(db, admin, admin.id, new_role="member")


def test_admin_reset_password(db):
    admin = create_test_admin(db, "admin5")
    user = create_user_admin(db, admin, "pw_target", "oldpass123456")
    create_login_session(db, user)
    db.commit()

    reset_user_password(db, admin, user.id, "brand_new_pass_456")

    # Old session is revoked
    assert (
        len(list(db.scalars(select(LoginSession).where(LoginSession.user_id == user.id)).all()))
        == 0
    )

    # Can authenticate with new password
    session, _ = authenticate_user(db, "127.0.0.1", "pw_target", "brand_new_pass_456")
    assert session.user_id == user.id


def test_admin_revoke_sessions(db):
    admin = create_test_admin(db, "admin6")
    user = create_user_admin(db, admin, "sess_target", "pass123456789")
    create_login_session(db, user)
    create_login_session(db, user)
    db.commit()

    revoked = revoke_user_sessions(db, admin, user.id)
    assert revoked == 2
    assert (
        len(list(db.scalars(select(LoginSession).where(LoginSession.user_id == user.id)).all()))
        == 0
    )


def test_list_users_paginated_and_filtered(db):
    admin = create_test_admin(db, "admin7")
    create_user_admin(db, admin, "alpha_member", "pass123456789", role="member")
    create_user_admin(db, admin, "beta_admin", "pass123456789", role="administrator")
    u3 = create_user_admin(db, admin, "gamma_disabled", "pass123456789", role="member")
    update_user_status(db, admin, u3.id, active=False)

    users, total = list_users_paginated(db, admin, search="alpha")
    assert total == 1
    assert users[0].username == "alpha_member"

    users, total = list_users_paginated(db, admin, role="administrator")
    assert any(u.username == "beta_admin" for u in users)

    users, total = list_users_paginated(db, admin, active=False)
    assert total == 1
    assert users[0].username == "gamma_disabled"
