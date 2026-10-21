from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from advanced_alchemy.types import FileObject
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.config import get_settings
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.documents import (
    delete_unreferenced_objects,
    list_expired_export_artifacts,
    retire_expired_export_artifacts,
)
from quirebase.models import FileRevision, Item, User
from quirebase.operations.maintenance import reconcile_objects


async def _user(db, username: str) -> User:
    user = User(username=username, password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    return user


@pytest.mark.anyio
async def test_reconciliation_deletes_only_old_unreferenced_managed_objects(
    async_db, fake_durable_operations
):
    store = get_object_store()
    referenced_id, orphan_id, active_pdf_id, active_thumbnail_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    referenced = await store.put_object(
        referenced_id, ObjectSuffix.PDF, b"referenced", max_bytes=20
    )
    orphan = await store.put_object(orphan_id, ObjectSuffix.BINARY, b"orphan", max_bytes=20)
    active_pdf = await store.put_object(
        active_pdf_id, ObjectSuffix.PDF, b"active pdf", max_bytes=20
    )
    active_thumbnail = await store.put_object(
        active_thumbnail_id, ObjectSuffix.PNG, b"active thumbnail", max_bytes=20
    )
    await store.put(".doctor/probe", b"probe")
    await store.put("unknown/layout.bin", b"unknown")
    cutoff = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    object_root = get_settings().object_dir
    os.utime(object_root / referenced.key, (cutoff, cutoff))
    os.utime(object_root / orphan.key, (cutoff, cutoff))
    os.utime(object_root / active_pdf.key, (cutoff, cutoff))
    os.utime(object_root / active_thumbnail.key, (cutoff, cutoff))

    user = await _user(async_db, "reconcile-owner")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        created_by=user.id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Referenced"},
    )
    async_db.add(item)
    await async_db.flush()
    async_db.add(
        FileRevision(
            workspace_id=fixture_workspace_id(user),
            item_id=item.id,
            created_by=user.id,
            file=FileObject(
                backend="documents",
                filename=referenced.key,
                size=referenced.size,
                content_type="application/pdf",
                metadata={"original_name": "referenced.pdf"},
            ),
        )
    )
    await async_db.commit()

    await fake_durable_operations.enqueue(
        "documents.upload_revision",
        queue_name="documents.upload",
        workflow_id="active-upload",
        attributes={"object_keys": [active_pdf.key, active_thumbnail.key]},
    )
    await fake_durable_operations.enqueue(
        "documents.cleanup_objects",
        queue_name="documents.cleanup",
        workflow_id="active-cleanup",
        attributes={"object_keys": [orphan.key], "object_intent": "cleanup"},
    )
    deleted = await reconcile_objects(async_db, retention_hours=1)

    assert deleted == (orphan.key,)
    assert await store.exists(referenced.key)
    assert await store.exists(active_pdf.key)
    assert await store.exists(active_thumbnail.key)
    assert await store.exists(".doctor/probe")
    assert await store.exists("unknown/layout.bin")


@pytest.mark.anyio
async def test_cleanup_exports_applies_runtime_ttl_to_annotation_objects(
    async_db,
):
    from quirebase.models import ExportArtifact

    store = get_object_store()
    expired = await store.put_object(uuid4(), ObjectSuffix.PDF, b"expired export", max_bytes=100)
    recent = await store.put_object(uuid4(), ObjectSuffix.PDF, b"recent export", max_bytes=100)
    now = datetime.now(UTC)
    user = await _user(async_db, "cleanup-owner")
    async_db.add_all([
        ExportArtifact(
            workflow_id="expired-export",
            workspace_id=fixture_workspace_id(user),
            actor_id=user.id,
            revision_id=uuid4(),
            expires_at=now - timedelta(seconds=1),
            file=FileObject(
                backend="documents",
                filename=expired.key,
                size=expired.size,
                content_type="application/pdf",
                metadata={"original_name": "expired.pdf"},
            ),
        ),
        ExportArtifact(
            workflow_id="recent-export",
            workspace_id=fixture_workspace_id(user),
            actor_id=user.id,
            revision_id=uuid4(),
            expires_at=now + timedelta(hours=1),
            file=FileObject(
                backend="documents",
                filename=recent.key,
                size=recent.size,
                content_type="application/pdf",
                metadata={"original_name": "recent.pdf"},
            ),
        ),
    ])
    await async_db.commit()

    artifacts = await list_expired_export_artifacts(async_db, 100)
    keys = await retire_expired_export_artifacts(async_db, artifacts)
    await async_db.commit()
    assert len(await delete_unreferenced_objects(async_db, keys)) == 1
    assert not await store.exists(expired.key)
    assert await store.exists(recent.key)
    assert await async_db.get(ExportArtifact, "expired-export") is None
    assert await async_db.get(ExportArtifact, "recent-export") is not None
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(get_settings().object_dir / recent.key, (old, old))
    assert await reconcile_objects(async_db, retention_hours=1) == ()
    assert await store.exists(recent.key)
