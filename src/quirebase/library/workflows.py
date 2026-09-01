from __future__ import annotations

from typing import Any

from dbos import DBOS

from quirebase.core.database import AsyncSessionLocal
from quirebase.search import search_index

from .tag_recommendations import handle_item_tag_recommendation, request_item_tag_recommendation

FILE_REVISION_CHANGED_WORKFLOW = "library.file_revision_changed"
RECOMMEND_TAGS_WORKFLOW = "library.recommend_tags"


@DBOS.step(retries_allowed=True, max_attempts=3)
async def apply_file_revision_changed(item_id: str, owner_id: str | None) -> None:
    async with AsyncSessionLocal() as db:
        await search_index(db).index_item(db, item_id)
        await request_item_tag_recommendation(db, item_id, owner_id=owner_id)
        await db.commit()


@DBOS.workflow(name=FILE_REVISION_CHANGED_WORKFLOW)
async def file_revision_changed_workflow(item_id: str, owner_id: str | None) -> None:
    await apply_file_revision_changed(item_id, owner_id)


@DBOS.step(retries_allowed=True, max_attempts=3)
async def generate_item_tag_recommendation(
    item_id: str,
    generation_token: int,
    workflow_id: str,
    owner_id: str | None,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        result = await handle_item_tag_recommendation(
            db, item_id, generation_token, workflow_id, owner_id
        )
        await db.commit()
        return result


@DBOS.workflow(name=RECOMMEND_TAGS_WORKFLOW)
async def recommend_tags_workflow(
    item_id: str,
    generation_token: int,
    workflow_id: str,
    owner_id: str | None,
) -> dict[str, Any]:
    return await generate_item_tag_recommendation(
        item_id, generation_token, workflow_id, owner_id
    )
