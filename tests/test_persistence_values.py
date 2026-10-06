from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update
from workspace_helpers import provision_initial_workspace

from quirebase.audit import record_event
from quirebase.models import AuditEvent, ImportBatch, Item, User


@pytest.mark.anyio
async def test_structured_values_and_audit_timestamps_share_the_mutation_transaction(async_db):
    user = User(username="structured-values", password_hash="unused")
    async_db.add(user)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, user)
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
    async_db.add_all([item, batch])
    await async_db.commit()
    item_id, actor_id = item.id, user.id
    assert item_id.version == 7 and batch.id.version == 7
    await async_db.refresh(item)
    await async_db.refresh(batch)
    assert item.updated_at == old
    assert batch.records[0]["custom_fields"] == {"rating": 5}

    await async_db.execute(
        update(Item)
        .where(Item.id == item_id)
        .values(custom_fields={"dataset": {"ids": ["a", "b", "c"]}})
    )
    event = record_event(
        async_db,
        actor_id,
        "item.update",
        "item",
        item_id,
        detail={"item_id": item_id, "at": old},
        target_ids=[item_id],
    )
    await async_db.flush()
    event_id = event.id
    await async_db.refresh(item)
    await async_db.refresh(event)
    assert item.updated_at > old and item.updated_at.tzinfo == UTC
    assert event.detail["item_id"] == str(item_id)
    assert event.target_ids == [str(item_id)]
    await async_db.rollback()
    await async_db.refresh(item)
    assert item.custom_fields == {"dataset": {"ids": ["a", "b"]}}
    assert item.updated_at == old
    assert await async_db.scalar(select(AuditEvent).where(AuditEvent.id == event_id)) is None

    explicit = datetime(2021, 1, 1, tzinfo=UTC)
    await async_db.execute(
        update(Item)
        .where(Item.id == item_id)
        .values(title="Explicit timestamp", updated_at=explicit)
    )
    await async_db.commit()
    await async_db.refresh(item)
    assert item.updated_at == explicit
