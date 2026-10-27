from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from advanced_alchemy.types import FileObject
from document_helpers import shared_annotation_context
from sqlalchemy import select

from quirebase.core.errors import ResourceUnavailable
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.documents import (
    purge_deleted_annotations,
    purge_deleted_replies,
    restore_annotation_reply,
    restore_document_annotation,
    retry_revision_inspection,
    workflows,
)
from quirebase.documents.events import FILE_REVISION_CHANGED_WORKFLOW
from quirebase.documents.read_models import list_item_revisions
from quirebase.models import (
    FileRevision,
    FileRevisionProcessingState,
    PdfAnnotation,
    PdfAnnotationReply,
)


@pytest.mark.anyio
async def test_expired_annotation_undo_is_denied_before_purge_and_cascades_replies(async_db):
    author, _, item, _, _, annotation, reply = await shared_annotation_context(
        async_db, "undo-expiry"
    )
    annotation.deleted_at = datetime.now(UTC) - timedelta(hours=25)
    annotation.version += 1
    await async_db.commit()
    with pytest.raises(ResourceUnavailable):
        await restore_document_annotation(
            async_db, author, item.workspace_id, item.id, annotation.id, annotation.version
        )
    assert (
        await purge_deleted_annotations(
            async_db, before=datetime.now(UTC) - timedelta(hours=24), limit=1
        )
        == 1
    )
    await async_db.commit()
    assert await async_db.get(PdfAnnotation, annotation.id, populate_existing=True) is None
    assert await async_db.get(PdfAnnotationReply, reply.id, populate_existing=True) is None
    assert await purge_deleted_annotations(async_db, before=datetime.now(UTC), limit=1) == 0


@pytest.mark.anyio
async def test_expired_reply_undo_is_denied_and_purge_preserves_live_parent(async_db):
    author, _, item, _, _, annotation, reply = await shared_annotation_context(
        async_db, "reply-undo-expiry"
    )
    reply.deleted_at = datetime.now(UTC) - timedelta(hours=25)
    await async_db.commit()
    with pytest.raises(ResourceUnavailable):
        await restore_annotation_reply(
            async_db, author, item.workspace_id, item.id, annotation.id, reply.id, reply.version
        )
    assert (
        await purge_deleted_replies(
            async_db, before=datetime.now(UTC) - timedelta(hours=24), limit=1
        )
        == 1
    )
    await async_db.commit()
    assert await async_db.get(PdfAnnotation, annotation.id, populate_existing=True) is not None


@pytest.mark.anyio
async def test_missing_inspection_is_visible_as_failed_and_retry_reuses_the_pdf(
    async_db, fake_durable_operations
):
    author, _, item, _, revision, _, _ = await shared_annotation_context(
        async_db, "inspection-retry"
    )
    revision.processing_state = FileRevisionProcessingState.pending
    revision.processing_workflow_id = "missing-inspection"
    await async_db.commit()
    summaries = await list_item_revisions(async_db, item.workspace_id, item.id)
    assert summaries[0].processing_state is FileRevisionProcessingState.failed
    original_key = revision.file.path
    workflow_id = await retry_revision_inspection(
        async_db, author, item.workspace_id, item.id, revision.id
    )
    assert workflow_id != "missing-inspection"
    assert revision.file.path == original_key
    assert revision.processing_state is FileRevisionProcessingState.pending
    assert fake_durable_operations.enqueues[-1]["args"][3] == original_key
    fake_durable_operations.workflows[workflow_id] = SimpleNamespace(state="running")
    count = len(fake_durable_operations.enqueues)
    assert (
        await retry_revision_inspection(async_db, author, item.workspace_id, item.id, revision.id)
        == workflow_id
    )
    assert len(fake_durable_operations.enqueues) == count


@pytest.mark.anyio
async def test_old_inspection_cannot_fail_or_parse_a_new_attempt(
    async_db, fake_durable_operations, monkeypatch
):
    author, _, item, _, revision, _, _ = await shared_annotation_context(
        async_db, "inspection-stale"
    )
    revision.processing_state = FileRevisionProcessingState.pending
    revision.processing_workflow_id = "new-inspection"
    await async_db.commit()
    await workflows.fail_revision_processing(revision.id, "old-inspection")

    async def unexpected(*_args, **_kwargs):
        await async_db.execute(select(FileRevision.id))
        pytest.fail("a stale attempt must not parse the PDF")

    monkeypatch.setattr(workflows, "_inspect_pdf_object", unexpected)
    result = await workflows.inspect_and_publish_revision(
        author.id, item.workspace_id, revision.id, revision.file.path, uuid4(), "old-inspection"
    )
    assert result == {"revision_id": revision.id, "item_id": item.id}
    await async_db.refresh(revision)
    assert revision.processing_state is FileRevisionProcessingState.pending
    assert revision.processing_workflow_id == "new-inspection"


@pytest.mark.anyio
async def test_pdf_publication_rolls_back_ready_and_search_if_event_enqueue_fails(
    async_db, fake_durable_operations, monkeypatch
):
    author, _, item, _, revision, _, _ = await shared_annotation_context(
        async_db, "inspection-atomic"
    )
    store = get_object_store()
    stored = await store.put_object(uuid4(), ObjectSuffix.PDF, b"%PDF-original", max_bytes=100)
    revision.file = FileObject(
        backend="documents",
        filename=stored.key,
        checksum=stored.checksum,
        size=stored.size,
        content_type="application/pdf",
        metadata={"original_name": "source.pdf"},
    )
    revision.processing_state = FileRevisionProcessingState.pending
    revision.processing_workflow_id = "inspection-atomic"
    await async_db.commit()

    async def inspected(*_args, **_kwargs):
        await async_db.execute(select(FileRevision.id))
        return {
            "size": stored.size,
            "checksum": stored.checksum,
            "thumbnail_object_key": "aa/bb/thumb.png",
            "thumbnail_size": 8,
            "thumbnail_checksum": "sha256:" + "a" * 64,
            "page_count": 1,
            "page_geometry": [],
            "full_text": "large extracted content",
        }

    async def fail_enqueue(*_args, **_kwargs):
        await async_db.execute(select(FileRevision.id))
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(workflows, "_inspect_pdf_object", inspected)
    monkeypatch.setattr(fake_durable_operations, "enqueue_in_transaction", fail_enqueue)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        await workflows.inspect_and_publish_revision(
            author.id, item.workspace_id, revision.id, stored.key, uuid4(), "inspection-atomic"
        )
    await async_db.refresh(revision)
    assert revision.processing_state is FileRevisionProcessingState.pending
    assert revision.full_text is None


@pytest.mark.anyio
async def test_committed_pdf_survives_lost_step_response_and_replays_without_reparsing(
    async_db, fake_durable_operations, monkeypatch
):
    author, _, item, _, revision, _, _ = await shared_annotation_context(
        async_db, "inspection-lost-response"
    )
    stored = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-original", max_bytes=100
    )
    revision.file = FileObject(
        backend="documents",
        filename=stored.key,
        checksum=stored.checksum,
        size=stored.size,
        content_type="application/pdf",
        metadata={"original_name": "source.pdf"},
    )
    revision.processing_state = FileRevisionProcessingState.pending
    revision.processing_workflow_id = "inspection-lost-response"
    await async_db.commit()
    attempts = []
    thumbnail_id = uuid4()

    async def inspected(*_args, **_kwargs):
        attempts.append("parse")
        stored = await get_object_store().put_object(
            thumbnail_id, ObjectSuffix.PNG, b"thumbnail", max_bytes=100
        )
        return {
            "size": revision.file.size,
            "checksum": "sha256:" + "a" * 64,
            "thumbnail_object_key": stored.key,
            "thumbnail_size": stored.size,
            "thumbnail_checksum": stored.checksum,
            "page_count": 1,
            "page_geometry": [],
            "full_text": "large extracted content",
        }

    monkeypatch.setattr(workflows, "_inspect_pdf_object", inspected)
    publish = workflows.inspect_and_publish_revision

    async def lose_response(*args):
        await publish(*args)
        raise ConnectionError("step result was lost after the business commit")

    monkeypatch.setattr(workflows, "inspect_and_publish_revision", lose_response)
    body = workflows.inspect_imported_revision_workflow.__wrapped__.__wrapped__
    args = (
        author.id,
        item.workspace_id,
        revision.id,
        revision.file.path,
        thumbnail_id,
        "inspection-lost-response",
    )
    with pytest.raises(ConnectionError):
        await body(*args)
    await async_db.refresh(revision)
    assert revision.processing_state is FileRevisionProcessingState.ready
    assert await get_object_store().exists(revision.thumbnail.path)
    monkeypatch.setattr(workflows, "inspect_and_publish_revision", publish)
    assert await body(*args) == {"revision_id": revision.id, "item_id": item.id}
    assert attempts == ["parse"]
    assert (
        sum(
            row["workflow_name"] == FILE_REVISION_CHANGED_WORKFLOW
            for row in fake_durable_operations.enqueues
        )
        == 1
    )
