from __future__ import annotations

import io
import json
import sqlite3

import pytest
from item_helpers import create_item_record as create_item
from sqlalchemy import select
from test_library_ui import pdf_bytes

from quirebase.core.crypto import hash_password
from quirebase.core.errors import ResourceUnavailable
from quirebase.core.storage import LocalObjectStore
from quirebase.documents.revisions import store_pdf_revision
from quirebase.library import (
    admin_delete_item,
    get_storage_metrics,
    list_global_items,
)
from quirebase.library.imports import commit_import_batch
from quirebase.models import AuditEvent, FileRevision, ImportBatch, Item, User


async def create_test_admin(db, username="admin_item_test"):
    admin = User(
        username=username,
        password_hash=hash_password("adminpass123456"),
        role="administrator",
        active=True,
    )
    db.add(admin)
    await db.commit()
    return admin


async def create_test_member(db, username="member_item_test"):
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
async def test_list_global_items_across_users(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin_lib_1")
    member1 = await create_test_member(db, "member_lib_1")
    member2 = await create_test_member(db, "member_lib_2")

    item1 = await create_item(
        db, member1, title="Quantum Computing Advances", authors="Alice", abstract="Paper 1"
    )
    item2 = await create_item(
        db, member2, title="Deep Learning Frontiers", authors="Bob", abstract="Paper 2"
    )

    items, total = await list_global_items(db, admin)
    assert total >= 2
    ids = [it.id for it in items]
    assert item1.id in ids
    assert item2.id in ids

    # Test search filter
    items, total = await list_global_items(db, admin, search="Quant")
    assert total == 1
    assert items[0].id == item1.id


@pytest.mark.anyio
async def test_list_global_items_searches_plaintext_across_title_markup(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin-rich-title-search")
    member = await create_test_member(db, "member-rich-title-search")
    item = await create_item(db, member, title="<i>Alpha</i> Beta", authors="Example")

    items, total = await list_global_items(db, admin, search="Alpha Beta")

    assert total == 1
    assert items[0].id == item.id


@pytest.mark.anyio
async def test_list_global_items_search_does_not_expand_every_fts_match_into_parameters(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin-large-search")
    member = await create_test_member(db, "member-large-search")
    for number in range(20):
        await create_item(db, member, title=f"Common indexed title {number}", authors="Example")

    raw = await db.connection()
    connection = (await raw.get_raw_connection()).driver_connection._conn
    previous_limit = connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 16)
    try:
        items, total = await list_global_items(db, admin, search="Common", page_size=5)
    finally:
        connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, previous_limit)

    assert total == 20
    assert len(items) == 5


@pytest.mark.anyio
async def test_non_admin_cannot_list_global_items(async_db):
    db = async_db
    member = await create_test_member(db, "member_lib_blocked")
    with pytest.raises(ResourceUnavailable, match="administrator required"):
        await list_global_items(db, member)


@pytest.mark.anyio
async def test_storage_metrics_calculation(async_db, tmp_path, monkeypatch):
    db = async_db
    admin = await create_test_admin(db, "admin_lib_storage")
    member = await create_test_member(db, "member_lib_storage")

    item = await create_item(db, member, title="Storage Test Paper", authors="Charlie")
    data = pdf_bytes()
    await store_pdf_revision(db, member, item.id, io.BytesIO(data), "sample.pdf")

    metrics = await get_storage_metrics(db, admin)
    assert metrics["items_count"] >= 1
    assert metrics["revisions_count"] >= 1
    assert metrics["revisions_bytes"] >= len(data)
    assert metrics["total_disk_bytes"] >= len(data)


@pytest.mark.anyio
async def test_admin_delete_item_cascades_and_cleans_storage(async_db, tmp_path, monkeypatch):
    db = async_db
    admin = await create_test_admin(db, "admin_lib_del")
    member = await create_test_member(db, "member_lib_del")

    item = await create_item(db, member, title="Item to be Admin Deleted", authors="Dave")
    data = pdf_bytes()
    revision = await store_pdf_revision(db, member, item.id, io.BytesIO(data), "delete_target.pdf")
    item_id, revision_id, admin_id = item.id, revision.id, admin.id
    store = LocalObjectStore()
    object_path = store.path(revision.object_key)
    assert object_path.is_file()

    # Admin deletes item
    await admin_delete_item(db, admin, item_id)

    # Database entity is deleted
    assert await db.get(Item, item_id) is None
    assert await db.get(FileRevision, revision_id) is None

    # Object store file is deleted
    assert not object_path.exists()

    # Audit event is recorded
    event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "admin.item.delete", AuditEvent.target_id == item_id
        )
    )
    assert event is not None
    assert event.actor_id == admin_id


@pytest.mark.anyio
async def test_admin_delete_item_preserves_shared_objects(async_db, tmp_path, monkeypatch):
    db = async_db
    admin = await create_test_admin(db, "admin_lib_share")
    member = await create_test_member(db, "member_lib_share")

    item1 = await create_item(db, member, title="Shared Item 1")
    item2 = await create_item(db, member, title="Shared Item 2")
    data = pdf_bytes()
    rev1 = await store_pdf_revision(db, member, item1.id, io.BytesIO(data), "same.pdf")
    rev2 = await store_pdf_revision(db, member, item2.id, io.BytesIO(data), "same.pdf")
    item1_id, item2_id = item1.id, item2.id
    assert rev1.object_key == rev2.object_key

    store = LocalObjectStore()
    object_path = store.path(rev1.object_key)
    assert object_path.is_file()

    # Delete item1
    await admin_delete_item(db, admin, item1_id)
    assert await db.get(Item, item1_id) is None
    assert await db.get(Item, item2_id) is not None

    # Object file MUST be preserved because item2 still references it!
    assert object_path.is_file()

    # Deleting item2 now removes the file
    await admin_delete_item(db, admin, item2_id)
    assert not object_path.exists()


@pytest.mark.anyio
async def test_admin_delete_item_preserves_object_referenced_by_pending_pdf_import(
    async_db, tmp_path, monkeypatch
):
    db = async_db
    admin = await create_test_admin(db, "admin_pending_import")
    member = await create_test_member(db, "member_pending_import")
    item = await create_item(db, member, title="Committed copy")
    revision = await store_pdf_revision(db, member, item.id, io.BytesIO(pdf_bytes()), "shared.pdf")
    object_path = LocalObjectStore().path(revision.object_key)
    batch = ImportBatch(
        owner_id=member.id,
        file_format="pdf",
        records=json.dumps([
            {
                "title": "Pending copy",
                "_pdf": {
                    "object_key": revision.object_key,
                    "sha256": revision.sha256,
                    "size": revision.size,
                    "original_name": "pending-copy.pdf",
                },
            }
        ]),
        errors="[]",
    )
    db.add(batch)
    await db.commit()

    await admin_delete_item(db, admin, item.id)

    assert object_path.is_file()
    await commit_import_batch(db, member, batch.id)
    imported = await db.scalar(select(Item).where(Item.title == "Pending copy"))
    assert imported is not None
    imported_revision = await db.scalar(
        select(FileRevision).where(FileRevision.item_id == imported.id)
    )
    assert imported_revision is not None
    assert imported_revision.object_key == revision.object_key
    assert object_path.is_file()


@pytest.mark.anyio
async def test_non_admin_cannot_admin_delete_item(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin_lib_prot")
    member = await create_test_member(db, "member_lib_prot")
    item = await create_item(db, admin, title="Protected Item")

    with pytest.raises(ResourceUnavailable, match="administrator required"):
        await admin_delete_item(db, member, item.id)
