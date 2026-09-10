from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dbos import DBOS
from sqlalchemy import select

from quirebase.core.workflows import SEARCH_QUEUE, ads, durable_operations
from quirebase.models import Item

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
        source_sequence = await db.scalar(select(Item.aggregate_sequence).where(Item.id == item_id))
    if source_sequence is None:
        return None
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
