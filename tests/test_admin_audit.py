from __future__ import annotations

import json

import pytest

from quirebase.audit import query_events, record_event
from quirebase.core.crypto import hash_password
from quirebase.core.errors import ResourceUnavailable
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


def test_query_events(db):
    admin = create_test_admin(db, "admin_aud_1")
    member = create_test_member(db, "member_aud_1")

    record_event(db, admin.id, "admin.test_action_1", "system", detail={"key": "val1"})
    record_event(db, member.id, "user.test_action_2", "item", "item-123", detail={"key": "val2"})
    db.commit()

    # Query all
    events, total = query_events(db, admin)
    assert total >= 2

    # Query by action
    events, total = query_events(db, admin, action="admin.test_action_1")
    assert total == 1
    assert events[0].action == "admin.test_action_1"

    # Query by actor
    events, total = query_events(db, admin, actor_id=member.id)
    assert total == 1
    assert events[0].actor_id == member.id

    # Query by search keyword
    events, total = query_events(db, admin, search="val2")
    assert total == 1
    assert events[0].action == "user.test_action_2"
    assert json.loads(events[0].detail or "") == {"key": "val2"}


def test_query_events_filters_and_paginates(db):
    admin = create_test_admin(db, "admin_aud_page")
    record_event(db, admin.id, "item.first", "item", "item-1")
    record_event(db, admin.id, "item.second", "item", "item-2")
    record_event(db, admin.id, "project.only", "project", "project-1")
    db.commit()

    first_page, total = query_events(db, admin, target_type="item", page=1, page_size=1)
    second_page, second_total = query_events(db, admin, target_type="item", page=2, page_size=1)

    assert total == second_total == 2
    assert len(first_page) == len(second_page) == 1
    assert first_page[0].id != second_page[0].id


def test_non_admin_cannot_query_events(db):
    member = create_test_member(db, "member_aud_blocked")
    with pytest.raises(ResourceUnavailable, match="administrator required"):
        query_events(db, member)
