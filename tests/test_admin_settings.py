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


async def create_test_admin(db, username="admin_settings_test"):
    admin = User(
        username=username,
        password_hash=hash_password("adminpass123456"),
        role="administrator",
        active=True,
    )
    db.add(admin)
    await db.commit()
    return admin


async def create_test_member(db, username="member_settings_test"):
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
async def test_get_and_update_runtime_settings(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin_set_1")

    # Initial settings reflect defaults
    initial = await get_runtime_settings(db)
    assert "metadata_contact_email" in initial
    assert "ncbi_api_key" in initial

    # Update runtime settings
    updates = {
        "metadata_contact_email": "librarian@univ.edu",
        "ncbi_api_key": "ncbi_secret_token_123",
        "session_days": 45,
    }
    await update_runtime_settings(db, admin, updates)

    # Verify get_runtime_settings returns updated values
    current = await get_runtime_settings(db)
    assert current["metadata_contact_email"] == "librarian@univ.edu"
    assert current["ncbi_api_key"] == "ncbi_secret_token_123"
    assert current["session_days"] == 45

    # Verify get_effective_setting returns updated values
    assert await get_effective_setting(db, "metadata_contact_email") == "librarian@univ.edu"
    assert await get_effective_setting(db, "ncbi_api_key") == "ncbi_secret_token_123"
    assert await get_effective_setting(db, "session_days") == 45

    # Verify audit event
    event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "system.settings_update",
            AuditEvent.actor_id == admin.id,
        )
    )
    assert event is not None


@pytest.mark.anyio
async def test_update_settings_rejects_unwhitelisted_keys(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin_set_2")
    with pytest.raises(ValidationFailure, match="cannot be modified at runtime"):
        await update_runtime_settings(db, admin, {"database_url": "sqlite:///malicious.db"})


@pytest.mark.anyio
async def test_non_admin_cannot_update_settings(async_db):
    db = async_db
    member = await create_test_member(db, "member_set_3")
    with pytest.raises(ResourceUnavailable, match="administrator required"):
        await update_runtime_settings(db, member, {"ncbi_api_key": "hacked"})


@pytest.mark.anyio
async def test_runtime_settings_applied_to_pdf_upload_limit(async_db, tmp_path, monkeypatch):
    db = async_db
    import io

    from item_helpers import create_item_record as create_item
    from test_library_ui import pdf_bytes

    from quirebase.core.config import get_settings
    from quirebase.core.errors import ValidationFailure
    from quirebase.documents import store_pdf_revision

    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    admin = await create_test_admin(db, "admin_set_limit")
    member = await create_test_member(db, "member_set_limit")
    item = await create_item(db, member, title="Limit Test")

    # Set runtime limit to 10 bytes (smaller than sample PDF)
    await update_runtime_settings(db, admin, {"max_pdf_bytes": 10})

    data = pdf_bytes()
    with pytest.raises(ValidationFailure, match="file exceeds configured size limit"):
        await store_pdf_revision(db, member, item.id, io.BytesIO(data), "test.pdf")


@pytest.mark.anyio
async def test_runtime_settings_applied_to_discovery_settings_model(async_db):
    db = async_db
    from quirebase.operations.settings import get_effective_settings_model

    admin = await create_test_admin(db, "admin_set_disc")
    await update_runtime_settings(
        db,
        admin,
        {
            "nasa_ads_token": "ads_live_token",
            "ieee_api_key": "ieee_live_key",
            "metadata_contact_email": "admin@live.org",
        },
    )

    settings_model = await get_effective_settings_model(db)
    assert settings_model.nasa_ads_token == "ads_live_token"
    assert settings_model.ieee_api_key == "ieee_live_key"
    assert settings_model.metadata_contact_email == "admin@live.org"
