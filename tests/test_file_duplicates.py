from __future__ import annotations

from uuid import uuid4

import pytest
from advanced_alchemy.types import FileObject
from sqlalchemy import event
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.storage import ObjectStore
from quirebase.library import find_duplicates
from quirebase.models import Attachment, FileRevision, FileRevisionProcessingState, Item, User

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


def descriptor(checksum, suffix=".pdf"):
    return FileObject(
        backend="documents", filename=f"{uuid4().hex}{suffix}", size=100, checksum=checksum
    )


async def owner(db):
    actor = User(username=f"pdf-owner-{uuid4()}", password_hash="hash")
    db.add(actor)
    await db.flush()
    await provision_initial_workspace(db, actor)
    await db.commit()
    return actor, fixture_workspace_id(actor)


async def item(db, actor, workspace_id):
    value = Item(
        workspace_id=workspace_id,
        created_by=actor.id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": str(uuid4())},
    )
    db.add(value)
    await db.flush()
    return value


def revision(db, actor, item, checksum, *, ready=True, thumbnail=None):
    db.add(
        FileRevision(
            workspace_id=item.workspace_id,
            item_id=item.id,
            created_by=actor.id,
            file=descriptor(checksum),
            thumbnail=thumbnail,
            processing_state=(
                FileRevisionProcessingState.ready if ready else FileRevisionProcessingState.pending
            ),
        )
    )


async def test_pdf_duplicates_group_distinct_items_using_ready_revision_checksums_only(
    persistence_db, monkeypatch
):
    db = persistence_db
    actor, workspace_id = await owner(db)
    checksum = "sha256:" + "a" * 64
    other_checksum = "sha256:" + "b" * 64
    outside_checksum = "sha256:" + "c" * 64
    first, second, third, pending, historical, attachment_only, thumbnail_only, singleton = [
        await item(db, actor, workspace_id) for _ in range(8)
    ]
    # Independent UUID objects and different bibliographic records share bytes.
    revision(db, actor, first, checksum)
    revision(db, actor, first, checksum)
    revision(db, actor, first, other_checksum)
    revision(db, actor, second, checksum)
    revision(db, actor, third, other_checksum)
    revision(db, actor, pending, checksum, ready=False)
    for blank in (None, "", " \t\r\n"):
        revision(db, actor, historical, blank)
    revision(db, actor, thumbnail_only, None, thumbnail=descriptor(checksum, ".png"))
    db.add(
        Attachment(
            workspace_id=workspace_id,
            item_id=attachment_only.id,
            created_by=actor.id,
            file=descriptor(checksum, ".bin"),
        )
    )
    revision(db, actor, singleton, outside_checksum)
    # Neither a repeated revision on one Item nor another Workspace supplies a match.
    revision(db, actor, singleton, outside_checksum)
    outsider, outside_id = await owner(db)
    outside = await item(db, outsider, outside_id)
    revision(db, outsider, outside, outside_checksum)
    await db.commit()

    def unexpected_object_io(*args, **kwargs):
        pytest.fail("duplicate scanning must not read or hash stored objects")

    for method in ("get", "head", "materialize", "put_object"):
        monkeypatch.setattr(ObjectStore, method, unexpected_object_io)
    statements = []

    def capture(execution):
        statements.append(execution.statement)

    event.listen(db.sync_session, "do_orm_execute", capture)
    try:
        scan = await find_duplicates(db, actor, workspace_id, "file")
    finally:
        event.remove(db.sync_session, "do_orm_execute", capture)
    assert scan.scanned == 4
    assert {frozenset(row.id for row in group) for group in scan.groups} == {
        frozenset((first.id, second.id)),
        frozenset((first.id, third.id)),
    }
    assert all(statement.is_select for statement in statements)
    assert any("HAVING count(" in str(statement) for statement in statements)


async def test_pdf_duplicate_coverage_does_not_count_unhashed_or_pending_items(persistence_db):
    db = persistence_db
    actor, workspace_id = await owner(db)
    scan = await find_duplicates(db, actor, workspace_id, "file")
    assert scan.scanned == 0 and scan.groups == []
    historical = await item(db, actor, workspace_id)
    revision(db, actor, historical, None)
    revision(db, actor, historical, "sha256:" + "d" * 64, ready=False)
    await db.commit()
    scan = await find_duplicates(db, actor, workspace_id, "file")
    assert scan.scanned == 0 and scan.groups == []
