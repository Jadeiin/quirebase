from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4, uuid5

import pytest

from quirebase.core.config import get_settings
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.models import FileRevision, Item, User
from quirebase.operations.maintenance import cleanup_exports, reconcile_objects
from quirebase.operations.object_migration import migrate_legacy_objects


@pytest.mark.anyio
async def test_shared_legacy_cas_migrates_to_independent_uuid_objects(async_db):
    content = b"%PDF-shared-legacy"
    old_key = "aa/bb/" + "0" * 64 + ".pdf"
    store = get_object_store()
    await store.put(old_key, content)
    user = User(username="migration-owner", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    first_item = Item(title="First", created_by=user.id)
    second_item = Item(title="Second", created_by=user.id)
    async_db.add_all([first_item, second_item])
    await async_db.flush()
    first = FileRevision(
        item_id=first_item.id,
        object_key=old_key,
        size=len(content),
        original_name="first.pdf",
        created_by=user.id,
    )
    second = FileRevision(
        item_id=second_item.id,
        object_key=old_key,
        size=len(content),
        original_name="second.pdf",
        created_by=user.id,
    )
    async_db.add_all([first, second])
    await async_db.commit()

    dry_run = await migrate_legacy_objects(async_db)
    assert dry_run.planned == 2
    assert first.object_key == old_key

    report = await migrate_legacy_objects(async_db, apply=True)
    await async_db.refresh(first)
    await async_db.refresh(second)
    assert report.references_updated == 2
    assert first.object_key != second.object_key
    assert await store.exists(first.object_key)
    assert await store.exists(second.object_key)
    assert not await store.exists(old_key)

    repeated = await migrate_legacy_objects(async_db, apply=True)
    assert repeated.planned == 0


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

    user = User(username="reconcile-owner", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    item = Item(title="Referenced", created_by=user.id)
    async_db.add(item)
    await async_db.flush()
    async_db.add(
        FileRevision(
            item_id=item.id,
            object_key=referenced.key,
            size=referenced.size,
            original_name="referenced.pdf",
            created_by=user.id,
        )
    )
    await async_db.commit()

    await fake_durable_operations.enqueue(
        "documents.upload_revision",
        queue_name="documents.upload",
        workflow_id="active-upload",
        attributes={"object_keys": [active_pdf.key, active_thumbnail.key]},
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
    async_db, fake_durable_operations, monkeypatch
):
    store = get_object_store()
    expired = await store.put_object(uuid4(), ObjectSuffix.PDF, b"expired export", max_bytes=100)
    recent = await store.put_object(uuid4(), ObjectSuffix.PDF, b"recent export", max_bytes=100)
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(get_settings().object_dir / expired.key, (old, old))

    await fake_durable_operations.enqueue(
        "documents.export_annotations",
        queue_name="documents.revision",
        workflow_id="expired-export",
        attributes={"operation": "annotation_export"},
    )
    await fake_durable_operations.enqueue(
        "documents.export_annotations",
        queue_name="documents.revision",
        workflow_id="recent-export",
        attributes={"operation": "annotation_export"},
    )
    for workflow_id, key in (("expired-export", expired.key), ("recent-export", recent.key)):
        workflow = fake_durable_operations.workflows[workflow_id]
        fake_durable_operations.workflows[workflow_id] = replace(
            workflow,
            state="succeeded",
            raw_status="SUCCESS",
            output={"object_key": key},
        )

    async def one_hour_ttl(*_args, **_kwargs):
        await asyncio.sleep(0)
        return 1

    monkeypatch.setattr("quirebase.operations.settings.get_effective_setting", one_hour_ttl)
    assert await cleanup_exports(async_db) == 1
    assert not await store.exists(expired.key)
    assert await store.exists(recent.key)


@pytest.mark.anyio
async def test_migration_repeat_cleans_legacy_thumbnail_when_target_is_recorded(async_db):
    store = get_object_store()
    user = User(username="thumbnail-migration-owner", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    item = Item(title="Thumbnail migration", created_by=user.id)
    async_db.add(item)
    await async_db.flush()
    revision = FileRevision(
        item_id=item.id,
        object_key="aa/bb/" + "1" * 64 + ".pdf",
        size=8,
        original_name="paper.pdf",
        created_by=user.id,
    )
    async_db.add(revision)
    await async_db.flush()
    thumbnail_id = uuid5(UUID("9a8c5b31-a356-5c30-884d-45c17722d8b8"), f"thumbnail:{revision.id}")
    revision.thumbnail_object_key = (
        f"{thumbnail_id.hex[:2]}/{thumbnail_id.hex[2:4]}/{thumbnail_id.hex}.png"
    )
    await async_db.commit()
    legacy = f"thumbnails/{revision.id}.png"
    await store.put(revision.object_key, b"%PDF-1.4")
    await store.put(legacy, b"legacy-thumbnail")
    report = await migrate_legacy_objects(async_db, apply=True)
    assert report.legacy_deleted >= 1
    assert not await store.exists(legacy)
