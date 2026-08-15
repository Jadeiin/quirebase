from __future__ import annotations

import pytest
from sqlalchemy import select

from quirebase.core.crypto import hash_password
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.models import AuditEvent, User
from quirebase.operations.settings import (
    get_effective_setting,
    get_runtime_settings,
    update_runtime_settings,
)


def create_test_admin(db, username="admin_settings_test"):
    admin = User(
        username=username,
        password_hash=hash_password("adminpass123456"),
        role="administrator",
        active=True,
    )
    db.add(admin)
    db.commit()
    return admin


def create_test_member(db, username="member_settings_test"):
    user = User(
        username=username,
        password_hash=hash_password("memberpass123456"),
        role="member",
        active=True,
    )
    db.add(user)
    db.commit()
    return user


def test_get_and_update_runtime_settings(db):
    admin = create_test_admin(db, "admin_set_1")

    # Initial settings reflect defaults
    initial = get_runtime_settings(db)
    assert "metadata_contact_email" in initial
    assert "ncbi_api_key" in initial

    # Update runtime settings
    updates = {
        "metadata_contact_email": "librarian@univ.edu",
        "ncbi_api_key": "ncbi_secret_token_123",
        "session_days": 45,
    }
    update_runtime_settings(db, admin, updates)

    # Verify get_runtime_settings returns updated values
    current = get_runtime_settings(db)
    assert current["metadata_contact_email"] == "librarian@univ.edu"
    assert current["ncbi_api_key"] == "ncbi_secret_token_123"
    assert current["session_days"] == 45

    # Verify get_effective_setting returns updated values
    assert get_effective_setting(db, "metadata_contact_email") == "librarian@univ.edu"
    assert get_effective_setting(db, "ncbi_api_key") == "ncbi_secret_token_123"
    assert get_effective_setting(db, "session_days") == 45

    # Verify audit event
    event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "system.settings_update",
            AuditEvent.actor_id == admin.id,
        )
    )
    assert event is not None


def test_update_settings_rejects_unwhitelisted_keys(db):
    admin = create_test_admin(db, "admin_set_2")
    with pytest.raises(ValidationFailure, match="cannot be modified at runtime"):
        update_runtime_settings(db, admin, {"database_url": "sqlite:///malicious.db"})


def test_non_admin_cannot_update_settings(db):
    member = create_test_member(db, "member_set_3")
    with pytest.raises(ResourceUnavailable, match="administrator required"):
        update_runtime_settings(db, member, {"ncbi_api_key": "hacked"})
