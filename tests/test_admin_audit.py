from __future__ import annotations

import pytest

from quirebase.core.crypto import hash_password
from quirebase.core.errors import ResourceUnavailable
from quirebase.library.audit import query_audit_events, record_audit_event
from quirebase.models import User


def create_test_admin(db, username="admin_audit_test"):
    admin = User(
        username=username,
        password_hash=hash_password("adminpass123456"),
        role="administrator",
        active=True,
    )
    db.add(admin)
    db.commit()
    return admin


def create_test_member(db, username="member_audit_test"):
    user = User(
        username=username,
        password_hash=hash_password("memberpass123456"),
        role="member",
        active=True,
    )
    db.add(user)
    db.commit()
    return user


def test_query_audit_events(db):
    admin = create_test_admin(db, "admin_aud_1")
    member = create_test_member(db, "member_aud_1")

    record_audit_event(db, admin.id, "admin.test_action_1", "system", detail={"key": "val1"})
    record_audit_event(
        db, member.id, "user.test_action_2", "item", "item-123", detail={"key": "val2"}
    )
    db.commit()

    # Query all
    events, total = query_audit_events(db, admin)
    assert total >= 2

    # Query by action
    events, total = query_audit_events(db, admin, action="admin.test_action_1")
    assert total == 1
    assert events[0].action == "admin.test_action_1"

    # Query by actor
    events, total = query_audit_events(db, admin, actor_id=member.id)
    assert total == 1
    assert events[0].actor_id == member.id

    # Query by search keyword
    events, total = query_audit_events(db, admin, search="val2")
    assert total == 1
    assert events[0].action == "user.test_action_2"


def test_non_admin_cannot_query_audit_events(db):
    member = create_test_member(db, "member_aud_blocked")
    with pytest.raises(ResourceUnavailable, match="administrator required"):
        query_audit_events(db, member)
