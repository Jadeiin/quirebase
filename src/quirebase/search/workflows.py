from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dbos import DBOS
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from quirebase.core.workflows import SEARCH_QUEUE, ads, durable_operations
from quirebase.models import SearchProjectionState

from .engine import search_index

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


SEARCH_CHANGED_WORKFLOW = "search.changed"


async def enqueue_search_changed(
    db: AsyncSession,
    item_id: str,
    source_sequence: int | None = None,
) -> str | None:
    """Transactionally enqueue a rebuild of one Item's derived Search view."""

    if source_sequence is None:
        state = await db.scalar(
            select(SearchProjectionState)
            .where(SearchProjectionState.item_id == item_id)
            .with_for_update()
        )
        if state is None:
            # Search state is deliberately independent of Item lifecycle so a
            # deletion intent can still remove an already-indexed Item.
            state = SearchProjectionState(item_id=item_id, requested_generation=1)
            try:
                async with db.begin_nested():
                    db.add(state)
                    await db.flush()
            except IntegrityError:
                state = await db.scalar(
                    select(SearchProjectionState)
                    .where(SearchProjectionState.item_id == item_id)
                    .with_for_update()
                )
                if state is None:
                    raise
            else:
                source_sequence = 1
        if source_sequence is None:
            state.requested_generation += 1
            await db.flush()
            source_sequence = state.requested_generation
    source_sequence = int(source_sequence)
    workflow_id = f"search-changed:{item_id}:{source_sequence}"
    await durable_operations().enqueue_in_transaction(
        db,
        SEARCH_CHANGED_WORKFLOW,
        item_id,
        source_sequence,
        queue_name=SEARCH_QUEUE,
        partition_key=item_id,
        workflow_id=workflow_id,
        attributes={
            "capability": "search",
            "operation": "search_changed",
            "item_id": item_id,
            "source_sequence": source_sequence,
        },
    )
    return workflow_id


@ads.transaction(isolation_level="SERIALIZABLE")
async def apply_search_changed(item_id: str, source_sequence: int) -> None:
    db = ads.sql_session()
    await search_index(db).index_item(db, item_id, source_sequence=source_sequence)


@DBOS.workflow(name=SEARCH_CHANGED_WORKFLOW)
async def search_changed_workflow(item_id: str, source_sequence: int) -> dict[str, Any]:
    await apply_search_changed(item_id, source_sequence)
    return {"item_id": item_id, "source_sequence": source_sequence}
