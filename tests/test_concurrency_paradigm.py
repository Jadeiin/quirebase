from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

import quirebase.documents.workflows as document_workflows
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.documents import create_attachment, store_pdf_revision
from quirebase.documents.annotations import (
    create_annotation_reply,
    create_document_annotation,
    delete_document_annotation,
)
from quirebase.documents.schemas import (
    AnnotationCreate,
    AnnotationKind,
    AnnotationReplyCreate,
    AnnotationScope,
)
from quirebase.library.imports import commit_import_batch
from quirebase.library.item_lifecycle import begin_item_deletion, validate_item_lifecycle_fence
from quirebase.models import (
    Attachment,
    FileRevision,
    FileRevisionProcessingState,
    ImportBatch,
    Item,
    ItemLifecycleState,
    ItemTag,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectRole,
    Tag,
    User,
)
from quirebase.search import search_index


@pytest.mark.anyio
async def test_item_create_operation_id_returns_the_original_item(async_db):
    from sqlalchemy import func, select

    from quirebase.library import create_item
    from quirebase.library.item_metadata import ItemMetadata

    db = async_db
    user = User(username="create_idem_user", password_hash="hash")
    other = User(username="create_idem_other", password_hash="hash")
    db.add_all([user, other])
    await db.flush()

    operation_id = "item-create:5b6f5d0a-1e5d-4e8d-9f0a-2c1b3d4e5f6a"
    first = await create_item(
        db, user, ItemMetadata(title="Idempotent Paper"), operation_id=operation_id
    )
    second = await create_item(
        db, user, ItemMetadata(title="Idempotent Paper"), operation_id=operation_id
    )

    assert first.item_id == second.item_id
    duplicates = await db.scalar(
        select(func.count()).select_from(Item).where(Item.create_operation_id == operation_id)
    )
    assert duplicates == 1

    # Keys are scoped per owner: the same key under another User is a separate
    # operation and must neither replay nor suppress the first User's Item.
    foreign = await create_item(
        db, other, ItemMetadata(title="Other Paper"), operation_id=operation_id
    )
    assert foreign.item_id != first.item_id
    assert foreign.item_id == (
        await db.scalar(
            select(Item.id).where(
                Item.created_by == other.id, Item.create_operation_id == operation_id
            )
        )
    )


@pytest.mark.anyio
async def test_upload_operation_id_replays_without_replacing_the_object(
    async_db, fake_durable_operations
):
    user = User(username="upload-replay-user", password_hash="hash")
    async_db.add(user)
    await async_db.flush()
    item = Item(title="Upload replay", created_by=user.id)
    async_db.add(item)
    await async_db.commit()

    operation_id = "2c9f8c3f-1dd8-4dc4-a2c0-2ea7f9e8a6c1"
    first = await store_pdf_revision(
        async_db, user, item.id, b"%PDF-first", "first.pdf", operation_id=operation_id
    )
    second = await store_pdf_revision(
        async_db, user, item.id, b"%PDF-second", "first.pdf", operation_id=operation_id
    )

    assert second == first
    assert len(fake_durable_operations.enqueues) == 1
    assert len(fake_durable_operations.messages) == 1

    with pytest.raises(ValidationFailure, match="already used"):
        await store_pdf_revision(
            async_db, user, item.id, b"%PDF-other", "other.pdf", operation_id=operation_id
        )


@pytest.mark.anyio
async def test_upload_releases_authorization_transaction_before_streaming(async_db):
    user = User(username="upload-lock-release-user", password_hash="hash")
    async_db.add(user)
    await async_db.flush()
    item = Item(title="Upload lock release", created_by=user.id)
    async_db.add(item)
    await async_db.commit()

    observed_transaction_state: list[bool] = []

    async def source():
        observed_transaction_state.append(async_db.in_transaction())
        await asyncio.sleep(0)
        yield b"%PDF-upload"

    await store_pdf_revision(async_db, user, item.id, source(), "release.pdf")
    assert observed_transaction_state == [False]


@pytest.mark.anyio
async def test_attachment_operation_id_replays_without_replacing_the_object(
    async_db, fake_durable_operations
):
    user = User(username="attachment-replay-user", password_hash="hash")
    async_db.add(user)
    await async_db.flush()
    item = Item(title="Attachment replay", created_by=user.id)
    async_db.add(item)
    await async_db.commit()

    operation_id = "b13d7548-ecb0-48ba-91f3-729302d0a9af"
    first = await create_attachment(
        async_db,
        user,
        item.id,
        b"first",
        "notes.txt",
        "text/plain",
        operation_id=operation_id,
    )
    second = await create_attachment(
        async_db,
        user,
        item.id,
        b"second",
        "notes.txt",
        "text/plain",
        operation_id=operation_id,
    )

    assert second == first
    assert len(fake_durable_operations.enqueues) == 1
    assert len(fake_durable_operations.messages) == 1

    with pytest.raises(ValidationFailure, match="already used"):
        await create_attachment(
            async_db,
            user,
            item.id,
            b"other",
            "different.txt",
            "text/plain",
            operation_id=operation_id,
        )


@pytest.mark.anyio
@pytest.mark.skip(reason="SQLite is single-process only; PostgreSQL covers concurrency")
async def test_sqlite_item_create_waits_for_same_owner_operation_gate(async_session_factory):
    from sqlalchemy import func, select, update

    from quirebase.library import create_item
    from quirebase.library.item_metadata import ItemMetadata, ItemWriteResult

    operation_id = "item-create:concurrent-replay"
    async with async_session_factory() as setup_db:
        user = User(username="create_operation_race", password_hash="hash")
        setup_db.add(user)
        await setup_db.commit()
        user_id = user.id

    async with async_session_factory() as winner_db:
        await winner_db.execute(update(User).where(User.id == user_id).values(active=User.active))

        async def create() -> object:
            async with async_session_factory() as db:
                user = await db.get(User, user_id)
                assert user is not None
                try:
                    return await create_item(
                        db,
                        user,
                        ItemMetadata(title="Losing duplicate"),
                        operation_id=operation_id,
                    )
                except Exception as error:
                    return error

        replay = asyncio.create_task(create())
        await asyncio.sleep(0.05)
        assert not replay.done()
        winner = Item(
            title="Winning Item",
            created_by=user_id,
            create_operation_id=operation_id,
        )
        winner_db.add(winner)
        await winner_db.commit()

    result = await replay
    assert isinstance(result, ItemWriteResult), result
    assert result.item_id == winner.id
    async with async_session_factory() as check_db:
        count = await check_db.scalar(
            select(func.count())
            .select_from(Item)
            .where(Item.created_by == user_id, Item.create_operation_id == operation_id)
        )
        assert count == 1


@pytest.mark.anyio
async def test_empty_item_create_operation_id_is_not_persisted(async_db):
    from sqlalchemy import select

    from quirebase.library import create_item
    from quirebase.library.item_metadata import ItemMetadata

    db = async_db
    user = User(username="empty_create_idem_user", password_hash="hash")
    db.add(user)
    await db.flush()

    first = await create_item(db, user, ItemMetadata(title="First Item"), operation_id="")
    second = await create_item(db, user, ItemMetadata(title="Second Item"), operation_id="")

    assert first.operation_id is None
    assert second.operation_id is None
    assert first.item_id != second.item_id
    stored = list(
        await db.scalars(
            select(Item.create_operation_id)
            .where(Item.id.in_((first.item_id, second.item_id)))
            .order_by(Item.id)
        )
    )
    assert stored == [None, None]


@pytest.mark.anyio
@pytest.mark.skip(reason="SQLite does not provide the supported PostgreSQL concurrency contract")
async def test_item_deletion_advances_fence_rejects_in_flight_workflow_commit(async_db):
    db = async_db
    user = User(username="fence_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Fenced Item", created_by=user.id)
    db.add(item)
    await db.commit()

    assert item.lifecycle_state == ItemLifecycleState.active.value
    assert item.lifecycle_fence == 1

    # In-flight workflow captured lifecycle_fence=1 at enqueue time
    captured_fence = item.lifecycle_fence

    # Concurrent deletion begins, which transitions state to deleting and advances fence
    new_fence = await begin_item_deletion(db, item.id)
    assert new_fence == 2

    # Validation of old fence fails
    assert await validate_item_lifecycle_fence(db, item.id, captured_fence) is None

    # In-flight workflow commit step rejects the stale fence
    rev_id = str(uuid4())
    inspected = {
        "revision_id": rev_id,
        "object_key": "fence/test.pdf",
        "thumbnail_object_key": "fence/thumb.png",
        "thumbnail_size": 128,
        "size": 1024,
        "page_count": 1,
        "full_text": "Sample text",
        "page_geometry": "[]",
    }
    with pytest.raises(ValueError, match="Item lifecycle changed before upload commit"):
        await document_workflows.commit_uploaded_revision(
            item.id,
            user.id,
            "sample.pdf",
            inspected,
            lifecycle_fence=captured_fence,
        )


@pytest.mark.anyio
async def test_import_batch_idempotent_commit_returns_same_item_ids(async_db):
    from sqlalchemy import func, select

    db = async_db
    user = User(username="import_retry_user", password_hash="hash")
    db.add(user)
    await db.flush()

    records = [
        {"title": "Paper Alpha", "authors": "Alice A", "doi": "10.1000/alpha"},
        {"title": "Paper Beta", "authors": "Bob B", "doi": "10.1000/beta"},
    ]
    batch = ImportBatch(
        created_by=user.id,
        file_format="bibtex",
        original_name="references.bib",
        status="ready",
        records=json.dumps(records),
        errors="[]",
    )
    db.add(batch)
    await db.commit()

    # First commit
    committed_ids_1 = await commit_import_batch(db, user, batch.id)
    assert len(committed_ids_1) == 2

    # Verify batch is now committed
    await db.refresh(batch)
    assert batch.status == "committed"
    assert json.loads(batch.committed_item_ids) == list(committed_ids_1)

    # Retry commit with the same operation
    committed_ids_2 = await commit_import_batch(db, user, batch.id)
    assert committed_ids_1 == committed_ids_2

    # Verify no duplicate items created
    total_items = await db.scalar(
        select(func.count()).select_from(Item).where(Item.title.in_(["Paper Alpha", "Paper Beta"]))
    )
    assert total_items == 2


@pytest.mark.anyio
@pytest.mark.skip(reason="SQLite is single-process only; PostgreSQL covers concurrency")
async def test_concurrent_sqlite_import_commit_replays_the_winning_result(
    async_session_factory,
):
    async with async_session_factory() as setup_db:
        user = User(username="sqlite-import-race", password_hash="hash")
        setup_db.add(user)
        await setup_db.flush()
        batch = ImportBatch(
            created_by=user.id,
            file_format="bibtex",
            status="ready",
            records=json.dumps([{"title": "Imported once concurrently"}]),
            errors="[]",
        )
        setup_db.add(batch)
        await setup_db.commit()
        user_id, batch_id = user.id, batch.id

    start = asyncio.Event()

    async def commit() -> object:
        async with async_session_factory() as db:
            user = await db.get(User, user_id)
            assert user is not None
            await start.wait()
            return await commit_import_batch(db, user, batch_id, "same-operation")

    tasks = [asyncio.create_task(commit()), asyncio.create_task(commit())]
    start.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert not any(isinstance(result, BaseException) for result in results), results
    assert results[0] == results[1]


@pytest.mark.anyio
async def test_import_commit_rejects_operation_id_over_storage_limit(async_db):
    operation_id = "x" * 256
    db = async_db
    user = User(username=f"long_operation_{len(operation_id)}", password_hash="hash")
    db.add(user)
    await db.flush()
    batch = ImportBatch(
        created_by=user.id,
        file_format="bibtex",
        status="ready",
        records=json.dumps([{"title": "Bounded operation"}]),
        errors="[]",
    )
    db.add(batch)
    await db.commit()

    with pytest.raises(ValidationFailure, match="operation id is too long"):
        await commit_import_batch(db, user, batch.id, commit_operation_id=operation_id)

    await db.refresh(batch)
    assert batch.status == "ready"
    assert batch.commit_operation_id is None


@pytest.mark.anyio
@pytest.mark.parametrize("operation_id", ["x" * 249, "x" * 255])
async def test_import_commit_bounds_derived_item_operation_id(async_db, operation_id):
    db = async_db
    user = User(username=f"bounded_operation_{len(operation_id)}", password_hash="hash")
    db.add(user)
    await db.flush()
    batch = ImportBatch(
        created_by=user.id,
        file_format="bibtex",
        status="ready",
        records=json.dumps([{"title": "Bounded operation A"}, {"title": "Bounded operation B"}]),
        errors="[]",
    )
    db.add(batch)
    await db.commit()

    committed_ids = await commit_import_batch(db, user, batch.id, commit_operation_id=operation_id)

    items = [await db.get(Item, item_id) for item_id in committed_ids]
    item_operation_ids = {item.create_operation_id for item in items if item is not None}
    assert len(item_operation_ids) == 2
    assert all(
        operation_id is not None and len(operation_id) <= 255 for operation_id in item_operation_ids
    )
    assert (
        await commit_import_batch(db, user, batch.id, commit_operation_id=operation_id)
        == committed_ids
    )


@pytest.mark.anyio
async def test_annotation_root_deletion_invalidates_reply_creation(async_db):
    db = async_db
    user = User(username="annotator", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Annotated Document", created_by=user.id)
    db.add(item)
    await db.flush()

    project = Project(name="Test Project", created_by=user.id)
    db.add(project)
    await db.flush()

    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.owner))
    db.add(ProjectItem(project_id=project.id, item_id=item.id))
    await db.flush()

    revision = FileRevision(
        item_id=item.id,
        object_key="anno/test.pdf",
        size=1024,
        original_name="test.pdf",
        created_by=user.id,
        page_count=1,
        page_geometry="[[0, 0, 612, 792]]",
        processing_state=FileRevisionProcessingState.ready,
    )
    db.add(revision)
    await db.commit()

    # Create root annotation
    annotation_id = uuid4()
    root_view = await create_document_annotation(
        db,
        user,
        item.id,
        AnnotationCreate(
            id=annotation_id,
            revision_id=revision.id,
            page_index=0,
            kind=AnnotationKind.note,
            scope=AnnotationScope.private,
            payload={"type": "note", "rect": {"x": 10, "y": 10, "width": 20, "height": 20}},
        ),
    )
    assert root_view["id"] == str(annotation_id)

    # Delete root annotation
    await delete_document_annotation(db, user, item.id, str(annotation_id), version=1)

    # Attempting to add a reply to the deleted root annotation must fail
    reply_id = uuid4()
    with pytest.raises(ResourceUnavailable, match="annotation not found or cannot be viewed"):
        await create_annotation_reply(
            db,
            user,
            item.id,
            str(annotation_id),
            AnnotationReplyCreate(id=reply_id, body="Late reply to deleted note"),
        )


@pytest.mark.anyio
async def test_search_index_drops_out_of_order_lower_sequence_updates(async_db):
    db = async_db
    user = User(username="search_monotonic_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Quantum Computing Advances", created_by=user.id)
    item.aggregate_sequence = 5
    db.add(item)
    await db.commit()

    idx = search_index(db)
    await idx.index_item(db, item.id, source_sequence=5)

    # Search matches
    assert await idx.search(db, "Quantum") == [item.id]

    # Stale update with lower source_sequence arrives out of order
    item.title = "Classical Newtonian Mechanics"
    await db.commit()
    await idx.index_item(db, item.id, source_sequence=3)

    # The stale update was dropped: search still has the sequence 5 index
    assert await idx.search(db, "Quantum") == [item.id]
    assert await idx.search(db, "Newtonian") == []

    # A newer update with higher source_sequence is applied
    await idx.index_item(db, item.id, source_sequence=6)
    assert await idx.search(db, "Quantum") == []
    assert await idx.search(db, "Newtonian") == [item.id]


@pytest.mark.anyio
@pytest.mark.skip(reason="SQLite is single-process only; PostgreSQL covers concurrency")
async def test_concurrent_sqlite_search_commits_keep_the_highest_sequence(
    async_session_factory,
):
    from sqlalchemy import text, update

    async with async_session_factory() as setup_db:
        user = User(username="sqlite-search-race", password_hash="hash")
        setup_db.add(user)
        await setup_db.flush()
        item = Item(title="Old projection", created_by=user.id)
        setup_db.add(item)
        await setup_db.commit()
        item_id = item.id
        await search_index(setup_db).index_item(setup_db, item_id, source_sequence=1)
        await setup_db.commit()

    async def project() -> None:
        async with async_session_factory() as db:
            await search_index(db).index_item(db, item_id, source_sequence=2)
            await db.commit()

    async with async_session_factory() as mutation_db:
        await mutation_db.execute(
            update(Item).where(Item.id == item_id).values(title="Newest projection")
        )
        projection = asyncio.create_task(project())
        await asyncio.sleep(0.05)
        assert not projection.done()
        await mutation_db.commit()
        await projection

    async with async_session_factory() as check_db:
        stored_sequence = await check_db.scalar(
            text("SELECT source_sequence FROM item_search WHERE item_id = :item_id"),
            {"item_id": item_id},
        )
        assert stored_sequence == 2
        assert await search_index(check_db).search(check_db, "Newest") == [item_id]
        assert await search_index(check_db).search(check_db, "Old") == []


@pytest.mark.anyio
async def test_set_item_tags_rejects_a_stale_collection_version(async_db):
    from sqlalchemy import select

    from quirebase.core.errors import VersionConflict
    from quirebase.library.tags import set_item_tags

    db = async_db
    user = User(username="collection_cas_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Collection CAS", created_by=user.id)
    db.add(item)
    await db.flush()

    await set_item_tags(
        db,
        user,
        item.id,
        [],
        ["Alpha"],
        expected_collection_version=item.tag_collection_version,
    )
    await db.refresh(item)
    assert item.version == 1
    assert item.tag_collection_version == 2

    with pytest.raises(VersionConflict):
        await set_item_tags(db, user, item.id, [], ["Beta"], expected_collection_version=1)

    await set_item_tags(
        db,
        user,
        item.id,
        [],
        ["Beta"],
        expected_collection_version=item.tag_collection_version,
    )
    assigned = list(
        (await db.scalars(select(Tag.name).join(ItemTag).where(ItemTag.item_id == item.id))).all()
    )
    assert assigned == ["Beta"]


@pytest.mark.anyio
async def test_tag_delta_invalidates_only_the_tag_collection_snapshot(async_db):
    from quirebase.core.errors import VersionConflict
    from quirebase.library.item_metadata import ItemMetadata, revise_item_metadata
    from quirebase.library.tags import add_tag_to_item, remove_tag_from_item, set_item_tags

    db = async_db
    user = User(username="incremental_tag_cas_user", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Incremental Tag CAS", created_by=user.id)
    db.add(item)
    await db.commit()

    assignment = await add_tag_to_item(db, user, item.id, "Concurrent")
    tag_id = assignment.tag_id
    await db.refresh(item)
    assert item.version == 1
    assert item.tag_collection_version == 2
    with pytest.raises(VersionConflict):
        await set_item_tags(db, user, item.id, [], expected_collection_version=1)

    metadata_result = await revise_item_metadata(
        db,
        user,
        item.id,
        expected_version=1,
        metadata=ItemMetadata(title="Metadata remains independently editable"),
    )
    assert metadata_result.version == 2

    await remove_tag_from_item(db, user, item.id, tag_id)
    await db.refresh(item)
    assert item.version == 2
    assert item.tag_collection_version == 3
    with pytest.raises(VersionConflict):
        await set_item_tags(db, user, item.id, [], expected_collection_version=2)


@pytest.mark.anyio
async def test_bulk_tag_assignment_invalidates_a_stale_collection_snapshot(async_db):
    from quirebase.core.errors import VersionConflict
    from quirebase.library.bulk_items import apply_bulk_item_action
    from quirebase.library.tags import set_item_tags

    db = async_db
    user = User(username="bulk_tag_cas_user", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Bulk Tag CAS", created_by=user.id)
    db.add(item)
    await db.commit()

    await apply_bulk_item_action(db, user, [item.id], "add_tag", tag_name="Concurrent")
    await db.refresh(item)
    assert item.version == 1
    assert item.tag_collection_version == 2

    with pytest.raises(VersionConflict):
        await set_item_tags(db, user, item.id, [], expected_collection_version=1)


@pytest.mark.anyio
@pytest.mark.skip(reason="obsolete broad Project grant locking seam was removed")
async def test_upload_edit_scope_locks_projects_before_the_item(monkeypatch):
    import quirebase.access.items as item_access

    events = []

    sentinel = object()

    async def lock_item(_db, item_id, lifecycle_fence):  # ruff: ignore[unused-async]
        events.append(f"item:{item_id}:{lifecycle_fence}")
        return sentinel

    monkeypatch.setattr(item_access, "lock_item_lifecycle_fence", lock_item)
    result = await item_access.lock_item_edit_scope(object(), "item-id", 7)

    # Lifecycle-only workflows no longer enumerate unrelated Project grants;
    # actor-bound commands use lock_item_edit_authority instead.
    assert result is sentinel
    assert events == ["item:item-id:7"]


@pytest.mark.anyio
@pytest.mark.skip(reason="obsolete broad Project grant locking seam was removed")
async def test_item_project_gates_are_locked_in_stable_order():
    from quirebase.access.items import lock_item_project_gates

    locked = []

    class RecordingSession:
        async def scalars(self, _statement):
            return ("project-z", "project-a", "project-z")

        async def scalar(self, statement):
            locked.append(statement.compile().params["id_1"])
            return locked[-1]

    project_ids = await lock_item_project_gates(RecordingSession(), ("item-id",))

    assert project_ids == ("project-a", "project-z")
    assert locked == ["project-a", "project-z"]


@pytest.mark.anyio
async def test_upload_commit_reauthorizes_the_captured_owner(async_db):
    db = async_db
    owner = User(username="upload_owner", password_hash="hash")
    stranger = User(username="upload_stranger", password_hash="hash")
    db.add_all([owner, stranger])
    await db.flush()

    item = Item(title="Owner Gate", created_by=owner.id)
    db.add(item)
    await db.commit()

    fence = item.lifecycle_fence
    inspected = {
        "revision_id": str(uuid4()),
        "object_key": "gate/test.pdf",
        "thumbnail_object_key": "gate/thumb.png",
        "thumbnail_size": 128,
        "size": 1024,
        "page_count": 1,
        "full_text": "Sample text",
        "page_geometry": "[]",
    }

    # A captured owner whose access was revoked cannot commit the upload.
    with pytest.raises(ValueError, match="no longer writable"):
        await document_workflows.commit_uploaded_revision(
            item.id, stranger.id, "sample.pdf", inspected, lifecycle_fence=fence
        )

    # The owner who still may edit the Item commits deterministically.
    result = await document_workflows.commit_uploaded_revision(
        item.id, owner.id, "sample.pdf", inspected, lifecycle_fence=fence
    )
    assert result["revision_id"] == inspected["revision_id"]

    receipt = {"object_key": "gate/data.bin", "size": 256}
    with pytest.raises(ValueError, match="no longer writable"):
        await document_workflows.commit_uploaded_attachment(
            item.id,
            stranger.id,
            str(uuid4()),
            "data.bin",
            "application/octet-stream",
            None,
            receipt,
            lifecycle_fence=fence,
        )


@pytest.mark.anyio
async def test_upload_commit_rejects_deactivated_owner(async_db):
    db = async_db
    owner = User(username="deactivated_owner", password_hash="hash")
    db.add(owner)
    await db.flush()

    item = Item(title="Deactivated Owner", created_by=owner.id)
    db.add(item)
    await db.commit()

    fence = item.lifecycle_fence
    owner.active = False
    await db.commit()

    inspected = {
        "revision_id": str(uuid4()),
        "object_key": "gate/dead.pdf",
        "thumbnail_object_key": "gate/thumb.png",
        "thumbnail_size": 128,
        "size": 1024,
        "page_count": 1,
        "full_text": "Sample text",
        "page_geometry": "[]",
    }
    # Session and token revocation accompany deactivation; the durable upload
    # must not commit for a user who is no longer active.
    with pytest.raises(ValueError, match="no longer writable"):
        await document_workflows.commit_uploaded_revision(
            item.id, owner.id, "sample.pdf", inspected, lifecycle_fence=fence
        )


@pytest.mark.anyio
async def test_upload_commit_serializes_with_membership_revocation(async_db):
    from sqlalchemy import delete

    db = async_db
    owner = User(username="project_editor_owner", password_hash="hash")
    project_owner = User(username="project_owner_user", password_hash="hash")
    db.add_all([owner, project_owner])
    await db.flush()

    item = Item(title="Shared Upload", created_by=project_owner.id)
    project = Project(name="Upload Project", created_by=project_owner.id)
    db.add_all([item, project])
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=project_owner.id, role=ProjectRole.owner))
    db.add(ProjectMember(project_id=project.id, user_id=owner.id, role=ProjectRole.editor))
    db.add(ProjectItem(project_id=project.id, item_id=item.id))
    await db.commit()

    fence = item.lifecycle_fence
    inspected = {
        "revision_id": str(uuid4()),
        "object_key": "gate/shared.pdf",
        "thumbnail_object_key": "gate/thumb.png",
        "thumbnail_size": 128,
        "size": 1024,
        "page_count": 1,
        "full_text": "Sample text",
        "page_geometry": "[]",
    }

    # While the editor membership exists the upload commits.
    result = await document_workflows.commit_uploaded_revision(
        item.id, owner.id, "sample.pdf", inspected, lifecycle_fence=fence
    )
    assert result["revision_id"] == inspected["revision_id"]

    # After the granting membership is revoked the same durable workflow can
    # no longer authorize its final write.
    await db.execute(delete(ProjectMember).where(ProjectMember.user_id == owner.id))
    await db.commit()
    second_upload = dict(inspected, revision_id=str(uuid4()))
    with pytest.raises(ValueError, match="no longer writable"):
        await document_workflows.commit_uploaded_revision(
            item.id, owner.id, "sample.pdf", second_upload, lifecycle_fence=fence
        )


@pytest.mark.anyio
async def test_committed_batch_stops_reserving_staged_pdf(async_db):
    from sqlalchemy import select

    from quirebase.documents.revisions import _referenced_candidates
    from quirebase.models import FileRevision

    db = async_db
    user = User(username="batch_reserve_user", password_hash="hash")
    db.add(user)
    await db.flush()

    staged_key = "staging/objects/reserved.pdf"
    records = [
        {
            "title": "Reserved Paper",
            "_pdf": {"object_key": staged_key, "size": 10, "original_name": "reserved.pdf"},
        }
    ]
    batch = ImportBatch(
        created_by=user.id,
        file_format="pdf",
        status="ready",
        records=json.dumps(records),
        errors="[]",
    )
    db.add(batch)
    await db.commit()

    # A non-terminal batch reserves its staged object against cleanup.
    assert staged_key in await _referenced_candidates(db, (staged_key,))

    committed_ids = await commit_import_batch(db, user, batch.id)
    assert len(committed_ids) == 1

    await db.refresh(batch)
    assert batch.status == "committed"
    assert all("_pdf" not in record for record in json.loads(batch.records))

    # The staged key is now owned by the created FileRevision, not the batch.
    item_id = committed_ids[0]
    revision = await db.scalar(select(FileRevision).where(FileRevision.item_id == item_id))
    assert revision is not None and revision.object_key == staged_key
    await db.delete(revision)
    await db.commit()
    # Deleting the resulting Item therefore frees the object for cleanup —
    # the committed tombstone no longer reserves the key.
    assert staged_key not in await _referenced_candidates(db, (staged_key,))


@pytest.mark.anyio
async def test_deleting_item_is_hidden_from_project_member_reads(async_db):
    from quirebase.access.items import can_read_item

    db = async_db
    creator = User(username="deleting_creator", password_hash="hash")
    member = User(username="deleting_member", password_hash="hash")
    db.add_all([creator, member])
    await db.flush()

    item = Item(title="Dying Item", created_by=creator.id)
    project = Project(name="Dying Project", created_by=creator.id)
    db.add_all([item, project])
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=creator.id, role=ProjectRole.owner))
    db.add(ProjectMember(project_id=project.id, user_id=member.id, role=ProjectRole.viewer))
    db.add(ProjectItem(project_id=project.id, item_id=item.id))
    await db.commit()

    assert await can_read_item(db, member, item.id) is True
    assert await can_read_item(db, creator, item.id) is True

    item.lifecycle_state = ItemLifecycleState.deleting
    await db.commit()

    # A deletion tombstone must not stay readable through the shared link.
    assert await can_read_item(db, member, item.id) is False
    assert await can_read_item(db, creator, item.id) is False


@pytest.mark.anyio
async def test_item_create_rejects_an_overlong_operation_id(async_db):
    from sqlalchemy import func, select

    from quirebase.core.errors import ValidationFailure
    from quirebase.library import create_item
    from quirebase.library.item_metadata import ItemMetadata

    db = async_db
    user = User(username="overlong_op_user", password_hash="hash")
    db.add(user)
    await db.flush()

    with pytest.raises(ValidationFailure):
        await create_item(db, user, ItemMetadata(title="Too Long"), operation_id="x" * 256)

    # The rejected operation must not leave a half-created aggregate behind.
    created = await db.scalar(
        select(func.count()).select_from(Item).where(Item.created_by == user.id)
    )
    assert created == 0


@pytest.mark.anyio
async def test_discard_after_commit_preserves_the_idempotency_record(async_db):
    db = async_db
    user = User(username="discard_late_user", password_hash="hash")
    db.add(user)
    await db.flush()

    batch = ImportBatch(
        created_by=user.id,
        file_format="bibtex",
        status="ready",
        records=json.dumps([{"title": "Late Discard", "doi": "10.1000/late"}]),
        errors="[]",
    )
    db.add(batch)
    await db.commit()

    from quirebase.library.imports import BatchConflict, discard_import_batch

    committed_ids = await commit_import_batch(db, user, batch.id)
    assert len(committed_ids) == 1

    # A discard racing behind the commit must not delete the tombstone that
    # carries the committed result.
    with pytest.raises(BatchConflict):
        await discard_import_batch(db, user, batch.id)

    replayed = await commit_import_batch(db, user, batch.id)
    assert replayed == committed_ids


@pytest.mark.anyio
@pytest.mark.skip(reason="SQLite is single-process only; PostgreSQL covers concurrency")
async def test_sqlite_discard_waits_for_concurrent_commit_gate(async_session_factory):
    from sqlalchemy import update

    from quirebase.library.imports import BatchConflict, discard_import_batch

    async with async_session_factory() as setup_db:
        user = User(username="discard_commit_race", password_hash="hash")
        setup_db.add(user)
        await setup_db.flush()
        batch = ImportBatch(
            created_by=user.id,
            file_format="bibtex",
            status="ready",
            records=json.dumps([{"title": "Commit wins"}]),
            errors="[]",
        )
        setup_db.add(batch)
        await setup_db.commit()
        user_id, batch_id = user.id, batch.id

    async with async_session_factory() as commit_db:
        await commit_db.execute(
            update(ImportBatch).where(ImportBatch.id == batch_id).values(status=ImportBatch.status)
        )

        async def discard() -> object:
            async with async_session_factory() as db:
                user = await db.get(User, user_id)
                assert user is not None
                try:
                    await discard_import_batch(db, user, batch_id)
                except Exception as error:
                    return error
                return None

        discard_result = asyncio.create_task(discard())
        await asyncio.sleep(0.05)
        assert not discard_result.done()
        await commit_db.execute(
            update(ImportBatch)
            .where(ImportBatch.id == batch_id)
            .values(status="committed", committed_item_ids="[]")
        )
        await commit_db.commit()

    assert isinstance(await discard_result, BatchConflict)


@pytest.mark.anyio
async def test_bulk_delete_gates_items_and_collects_all_child_keys(async_db):
    from quirebase.library.bulk_items import apply_bulk_item_action

    db = async_db
    user = User(username="bulk_cleanup_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Bulk cleanup", created_by=user.id)
    db.add(item)
    await db.flush()
    db.add(
        FileRevision(
            item_id=item.id,
            object_key="bulk/rev.pdf",
            thumbnail_object_key="bulk/thumb.png",
            size=10,
            original_name="rev.pdf",
            created_by=user.id,
            page_count=1,
            page_geometry="[]",
            processing_state=FileRevisionProcessingState.ready,
        )
    )
    db.add(
        Attachment(
            item_id=item.id,
            object_key="bulk/att.bin",
            size=10,
            mime_type="application/octet-stream",
            original_name="att.bin",
            created_by=user.id,
        )
    )
    await db.commit()

    cleanup_keys = await apply_bulk_item_action(
        db, user, [item.id], "delete", confirm_delete="delete"
    )
    assert set(cleanup_keys) == {"bulk/rev.pdf", "bulk/thumb.png", "bulk/att.bin"}
    assert await db.get(Item, item.id) is None


@pytest.mark.anyio
async def test_project_rename_and_delete_advance_item_sequences(async_db):
    from quirebase.projects.lifecycle import delete_project, rename_project

    db = async_db
    user = User(username="project_index_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Indexed item", created_by=user.id)
    project = Project(name="Original Project", created_by=user.id)
    db.add_all([item, project])
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.owner))
    db.add(ProjectItem(project_id=project.id, item_id=item.id))
    await db.commit()

    idx = search_index(db)
    sequence = item.aggregate_sequence

    await rename_project(db, user, project.id, "Renamed Project")
    await db.refresh(item)
    assert item.aggregate_sequence == sequence + 1
    await idx.index_item(db, item.id, source_sequence=item.aggregate_sequence)
    assert await idx.search(db, "Renamed") == [item.id]

    await delete_project(db, user, project.id, "Renamed Project")
    await db.refresh(item)
    assert item.aggregate_sequence == sequence + 2
    await idx.index_item(db, item.id, source_sequence=item.aggregate_sequence)
    assert await idx.search(db, "Renamed") == []


@pytest.mark.anyio
async def test_revision_deletion_invalidates_in_flight_recommendation(
    async_db, fake_durable_operations
):
    from sqlalchemy import select

    from quirebase.documents.revisions import delete_file_revision
    from quirebase.library.workflows import (
        commit_item_tag_recommendation_step,
        request_item_tag_recommendation,
    )
    from quirebase.models import ItemTagRecommendation

    db = async_db
    user = User(username="revision_delete_user", password_hash="hash")
    db.add(user)
    await db.flush()

    item = Item(title="Revision deletion", created_by=user.id)
    db.add(item)
    await db.flush()
    revision = FileRevision(
        item_id=item.id,
        object_key="lifecycle/rev.pdf",
        size=10,
        original_name="rev.pdf",
        created_by=user.id,
        page_count=1,
        page_geometry="[]",
        processing_state=FileRevisionProcessingState.ready,
    )
    db.add(revision)
    await db.commit()

    await request_item_tag_recommendation(db, item.id, owner_id=user.id)
    await db.commit()
    record = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item.id)
    )
    assert record is not None and record.source_sequence == 1

    # While the Item is still at the carried sequence the result lands.
    result = await commit_item_tag_recommendation_step(
        item.id,
        record.generation_token,
        record.workflow_id,
        {"single_words": ["fresh"], "phrases": []},
        source_sequence=1,
    )
    assert result == {"single_words": 1, "phrases": 0}

    item_id = item.id
    token = record.generation_token
    workflow_id = record.workflow_id

    # Deleting the revision advances both source sequences in the same
    # transaction, so a workflow still running against the deleted PDF can no
    # longer publish.
    await delete_file_revision(db, user, item_id, revision.id)
    sequence = await db.scalar(select(Item.aggregate_sequence).where(Item.id == item_id))
    assert sequence == 2
    recommendation_sequence = await db.scalar(
        select(Item.recommendation_sequence).where(Item.id == item_id)
    )
    assert recommendation_sequence == 2

    stale = await commit_item_tag_recommendation_step(
        item_id,
        token,
        workflow_id,
        {"single_words": ["stale"], "phrases": []},
        source_sequence=1,
    )
    assert stale == {"stale": True}
    await db.refresh(record)
    assert json.loads(record.single_words) == ["fresh"]


@pytest.mark.anyio
async def test_document_deletion_enqueues_durable_object_cleanup(async_db, fake_durable_operations):
    from quirebase.documents.events import OBJECT_CLEANUP_WORKFLOW
    from quirebase.documents.revisions import delete_attachment, delete_file_revision

    db = async_db
    user = User(username="durable_document_delete", password_hash="hash")
    db.add(user)
    await db.flush()
    item = Item(title="Durable document cleanup", created_by=user.id)
    db.add(item)
    await db.flush()
    revision = FileRevision(
        item_id=item.id,
        object_key="durable/revision.pdf",
        thumbnail_object_key="durable/revision.png",
        size=10,
        original_name="revision.pdf",
        created_by=user.id,
        processing_state=FileRevisionProcessingState.ready,
    )
    attachment = Attachment(
        item_id=item.id,
        object_key="durable/attachment.bin",
        size=10,
        mime_type="application/octet-stream",
        original_name="attachment.bin",
        created_by=user.id,
    )
    db.add_all([revision, attachment])
    await db.commit()
    user_id = user.id
    item_id = item.id
    revision_id = revision.id
    attachment_id = attachment.id

    await delete_file_revision(db, user, item_id, revision_id)
    user = await db.get(User, user_id)
    assert user is not None
    await delete_attachment(db, user, item_id, attachment_id)

    cleanup_requests = [
        enqueue
        for enqueue in fake_durable_operations.enqueues
        if enqueue["workflow_name"] == OBJECT_CLEANUP_WORKFLOW
    ]
    assert [set(request["args"][0]) for request in cleanup_requests] == [
        {"durable/revision.pdf", "durable/revision.png"},
        {"durable/attachment.bin"},
    ]
