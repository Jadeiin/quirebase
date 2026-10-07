from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from advanced_alchemy.types import FileObject
from sqlalchemy import event, select, update
from workspace_helpers import provision_initial_workspace

from quirebase.audit import record_event
from quirebase.documents import create_annotation_reply, create_document_annotation
from quirebase.documents.schemas import AnnotationCreate, AnnotationReplyCreate
from quirebase.models import (
    AuditEvent,
    FileRevision,
    ImportBatch,
    Item,
    PdfAnnotation,
    PdfAnnotationObject,
    PdfAnnotationReply,
    User,
)

pytestmark = pytest.mark.shared_postgres


@pytest.mark.anyio
async def test_client_annotation_ids_keep_one_native_uuid_session_identity(persistence_db):
    db = persistence_db
    actor = User(username="annotation-identity", password_hash="unused")
    db.add(actor)
    await db.flush()
    workspace = await provision_initial_workspace(db, actor)
    item = Item(workspace_id=workspace.id, created_by=actor.id, title="Annotations")
    db.add(item)
    await db.flush()
    revision = FileRevision(
        workspace_id=workspace.id,
        item_id=item.id,
        created_by=actor.id,
        page_count=1,
        page_geometry=[[0, 0, 100, 100]],
        processing_state="ready",
        file=FileObject(
            backend="documents",
            filename="objects/identity.pdf",
            size=100,
            metadata={"original_name": "identity.pdf"},
        ),
    )
    db.add(revision)
    await db.commit()
    inserted = []

    @event.listens_for(db.sync_session, "pending_to_persistent")
    def retain_inserted_identity(_session, instance):
        if isinstance(instance, (PdfAnnotation, PdfAnnotationReply, PdfAnnotationObject)):
            inserted.append(instance)

    annotation_id, reply_id = uuid4(), uuid4()
    annotation = await create_document_annotation(
        db,
        actor,
        workspace.id,
        item.id,
        AnnotationCreate.model_validate({
            "id": annotation_id,
            "revision_id": revision.id,
            "page_index": 0,
            "kind": "note",
            "body": "Original note",
            "payload": {"type": "note", "rect": {"x": 0, "y": 0, "width": 10, "height": 10}},
        }),
    )
    reply = await create_annotation_reply(
        db,
        actor,
        workspace.id,
        item.id,
        annotation_id,
        AnnotationReplyCreate(id=reply_id, body="Reply"),
    )
    assert str(annotation["id"]) == str(annotation_id)
    assert str(reply["id"]) == str(reply_id)
    assert len(inserted) == 4
    for instance in inserted:
        assert isinstance(instance.id, UUID) and instance.id.version == 4
        loaded = await db.scalar(select(type(instance)).where(type(instance).id == instance.id))
        assert loaded is instance
        assert await db.get(type(instance), instance.id) is instance
    assert (
        len([
            value
            for value in db.identity_map.values()
            if isinstance(value, (PdfAnnotation, PdfAnnotationReply, PdfAnnotationObject))
        ])
        == 4
    )


@pytest.mark.anyio
async def test_structured_values_and_audit_timestamps_share_the_mutation_transaction(
    persistence_db,
):
    user = User(username="structured-values", password_hash="unused")
    persistence_db.add(user)
    await persistence_db.flush()
    workspace = await provision_initial_workspace(persistence_db, user)
    old = datetime(2020, 1, 1, tzinfo=UTC)
    item = Item(
        workspace_id=workspace.id,
        created_by=user.id,
        title="JSON values",
        custom_fields={"dataset": {"ids": ["a", "b"]}},
        updated_at=old,
    )
    batch = ImportBatch(
        workspace_id=workspace.id,
        actor_id=user.id,
        file_format="bibtex",
        records=[{"title": "Candidate", "custom_fields": {"rating": 5}}],
        errors=[],
    )
    persistence_db.add_all([item, batch])
    await persistence_db.commit()
    item_id, actor_id = item.id, user.id
    assert item_id.version == 7 and batch.id.version == 7
    await persistence_db.refresh(item)
    await persistence_db.refresh(batch)
    assert item.updated_at == old
    assert batch.records[0]["custom_fields"] == {"rating": 5}

    await persistence_db.execute(
        update(Item)
        .where(Item.id == item_id)
        .values(custom_fields={"dataset": {"ids": ["a", "b", "c"]}})
    )
    event = record_event(
        persistence_db,
        actor_id,
        "item.update",
        "item",
        item_id,
        detail={"item_id": item_id, "at": old},
        target_ids=[item_id],
    )
    await persistence_db.flush()
    event_id = event.id
    await persistence_db.refresh(item)
    await persistence_db.refresh(event)
    assert item.updated_at > old and item.updated_at.utcoffset() == timedelta(0)
    assert event.detail["item_id"] == str(item_id)
    assert event.target_ids == [str(item_id)]
    await persistence_db.rollback()
    await persistence_db.refresh(item)
    assert item.custom_fields == {"dataset": {"ids": ["a", "b"]}}
    assert item.updated_at == old
    assert await persistence_db.scalar(select(AuditEvent).where(AuditEvent.id == event_id)) is None

    explicit = datetime(2021, 1, 1, tzinfo=UTC)
    await persistence_db.execute(
        update(Item)
        .where(Item.id == item_id)
        .values(title="Explicit timestamp", updated_at=explicit)
    )
    await persistence_db.commit()
    await persistence_db.refresh(item)
    assert item.updated_at == explicit
