from __future__ import annotations

import io

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
from quirebase.models import AuditEvent, FileRevision, Item, User


def create_test_admin(db, username="admin_item_test"):
    admin = User(
        username=username,
        password_hash=hash_password("adminpass123456"),
        role="administrator",
        active=True,
    )
    db.add(admin)
    db.commit()
    return admin


def create_test_member(db, username="member_item_test"):
    user = User(
        username=username,
        password_hash=hash_password("memberpass123456"),
        role="member",
        active=True,
    )
    db.add(user)
    db.commit()
    return user


def test_list_global_items_across_users(db):
    admin = create_test_admin(db, "admin_lib_1")
    member1 = create_test_member(db, "member_lib_1")
    member2 = create_test_member(db, "member_lib_2")

    item1 = create_item(
        db, member1, title="Quantum Computing Advances", authors="Alice", abstract="Paper 1"
    )
    item2 = create_item(
        db, member2, title="Deep Learning Frontiers", authors="Bob", abstract="Paper 2"
    )

    items, total = list_global_items(db, admin)
    assert total >= 2
    ids = [it.id for it in items]
    assert item1.id in ids
    assert item2.id in ids

    # Test search filter
    items, total = list_global_items(db, admin, search="Quantum")
    assert total == 1
    assert items[0].id == item1.id


def test_non_admin_cannot_list_global_items(db):
    member = create_test_member(db, "member_lib_blocked")
    with pytest.raises(ResourceUnavailable, match="administrator required"):
        list_global_items(db, member)


def test_storage_metrics_calculation(db, tmp_path, monkeypatch):
    admin = create_test_admin(db, "admin_lib_storage")
    member = create_test_member(db, "member_lib_storage")

    item = create_item(db, member, title="Storage Test Paper", authors="Charlie")
    data = pdf_bytes()
    store_pdf_revision(db, member, item.id, io.BytesIO(data), "sample.pdf")

    metrics = get_storage_metrics(db, admin)
    assert metrics["items_count"] >= 1
    assert metrics["revisions_count"] >= 1
    assert metrics["revisions_bytes"] >= len(data)
    assert metrics["total_disk_bytes"] >= len(data)


def test_admin_delete_item_cascades_and_cleans_storage(db, tmp_path, monkeypatch):
    admin = create_test_admin(db, "admin_lib_del")
    member = create_test_member(db, "member_lib_del")

    item = create_item(db, member, title="Item to be Admin Deleted", authors="Dave")
    data = pdf_bytes()
    revision = store_pdf_revision(db, member, item.id, io.BytesIO(data), "delete_target.pdf")
    store = LocalObjectStore()
    object_path = store.path(revision.object_key)
    assert object_path.is_file()

    # Admin deletes item
    admin_delete_item(db, admin, item.id)

    # Database entity is deleted
    assert db.get(Item, item.id) is None
    assert db.get(FileRevision, revision.id) is None

    # Object store file is deleted
    assert not object_path.exists()

    # Audit event is recorded
    event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "admin.item.delete", AuditEvent.target_id == item.id
        )
    )
    assert event is not None
    assert event.actor_id == admin.id


def test_admin_delete_item_preserves_shared_objects(db, tmp_path, monkeypatch):
    admin = create_test_admin(db, "admin_lib_share")
    member = create_test_member(db, "member_lib_share")

    item1 = create_item(db, member, title="Shared Item 1")
    item2 = create_item(db, member, title="Shared Item 2")
    data = pdf_bytes()
    rev1 = store_pdf_revision(db, member, item1.id, io.BytesIO(data), "same.pdf")
    rev2 = store_pdf_revision(db, member, item2.id, io.BytesIO(data), "same.pdf")
    assert rev1.object_key == rev2.object_key

    store = LocalObjectStore()
    object_path = store.path(rev1.object_key)
    assert object_path.is_file()

    # Delete item1
    admin_delete_item(db, admin, item1.id)
    assert db.get(Item, item1.id) is None
    assert db.get(Item, item2.id) is not None

    # Object file MUST be preserved because item2 still references it!
    assert object_path.is_file()

    # Deleting item2 now removes the file
    admin_delete_item(db, admin, item2.id)
    assert not object_path.exists()


def test_non_admin_cannot_admin_delete_item(db):
    admin = create_test_admin(db, "admin_lib_prot")
    member = create_test_member(db, "member_lib_prot")
    item = create_item(db, admin, title="Protected Item")

    with pytest.raises(ResourceUnavailable, match="administrator required"):
        admin_delete_item(db, member, item.id)
