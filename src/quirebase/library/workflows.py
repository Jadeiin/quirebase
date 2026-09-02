from __future__ import annotations

from typing import Any

from dbos import DBOS

from quirebase.core.workflows import ads
from quirebase.documents.events import FILE_REVISION_CHANGED_WORKFLOW
from quirebase.search import search_index

from .tag_recommendations import handle_item_tag_recommendation, request_item_tag_recommendation

RECOMMEND_TAGS_WORKFLOW = "library.recommend_tags"


@ads.transaction()
async def apply_file_revision_changed(item_id: str, owner_id: str | None) -> None:
    db = ads.sql_session()
    await search_index(db).index_item(db, item_id)
    await request_item_tag_recommendation(db, item_id, owner_id=owner_id)


@DBOS.workflow(name=FILE_REVISION_CHANGED_WORKFLOW)
async def file_revision_changed_workflow(item_id: str, owner_id: str | None) -> None:
    await apply_file_revision_changed(item_id, owner_id)


@ads.transaction()
async def generate_item_tag_recommendation(
    item_id: str,
    generation_token: int,
    workflow_id: str,
    owner_id: str | None,
) -> dict[str, Any]:
    db = ads.sql_session()
    return await handle_item_tag_recommendation(
        db, item_id, generation_token, workflow_id, owner_id
    )


@DBOS.workflow(name=RECOMMEND_TAGS_WORKFLOW)
async def recommend_tags_workflow(
    item_id: str,
    generation_token: int,
    workflow_id: str,
    owner_id: str | None,
) -> dict[str, Any]:
    return await generate_item_tag_recommendation(item_id, generation_token, workflow_id, owner_id)
