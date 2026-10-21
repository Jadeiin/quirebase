from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from advanced_alchemy.service import OffsetPagination
from fastapi import APIRouter, Query, status

from quirebase.library import (
    DuplicateMode,
    create_custom_citation_style,
    delete_custom_citation_style,
    delete_tag,
    find_duplicates,
    list_citation_styles,
    merge_tags,
    rename_tag,
)
from quirebase.web.api.common import OkView, WriteResult
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.library_schemas import (
    CitationStyleItemView,
    NameRequest,
    item_search_view,
)
from quirebase.web.api.tool_schemas import (
    CitationStyleCreateRequest,
    DuplicatesReviewView,
    TagMergeRequest,
)

router = APIRouter(tags=["Library tools"])


@router.get("/citation-styles", response_model=OffsetPagination[CitationStyleItemView])
async def citation_styles(
    workspace_id: UUID,
    user: ApiUser,
    db: Database,
    query: str = "",
    key: str = "",
    scope: Literal["", "builtin", "custom"] = "",
    sort: Literal["name"] = "name",
    direction: Literal["asc", "desc"] = "asc",
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OffsetPagination[CitationStyleItemView]:
    rows, total = await list_citation_styles(
        db,
        user,
        workspace_id,
        query=query,
        key=key,
        scope=scope,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    return OffsetPagination(
        items=[CitationStyleItemView(key=row.key, name=row.name, scope=row.scope) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/duplicates", response_model=DuplicatesReviewView)
async def duplicate_items(workspace_id: UUID, user: ApiUser, db: Database, mode: DuplicateMode):
    scan = await find_duplicates(db, user, workspace_id, mode)
    return {
        "groups": [[item_search_view(item) for item in group] for group in scan.groups],
        "scanned": scan.scanned,
    }


@router.post("/citation-styles", status_code=status.HTTP_201_CREATED)
async def create_citation_style(
    workspace_id: UUID, data: CitationStyleCreateRequest, user: ApiUser, db: Database
) -> WriteResult:
    style = await create_custom_citation_style(db, user, workspace_id, data.name, data.csl)
    return WriteResult(id=style.id)


@router.delete("/citation-styles/{style_id}")
async def delete_citation_style(
    workspace_id: UUID, style_id: UUID, user: ApiUser, db: Database
) -> OkView:
    await delete_custom_citation_style(db, user, workspace_id, style_id)
    return OkView()


@router.post("/tags/merge")
async def merge_user_tags(
    workspace_id: UUID, data: TagMergeRequest, user: ApiUser, db: Database
) -> OkView:
    await merge_tags(db, user, workspace_id, data.source_tag_id, data.target_tag_id)
    return OkView()


@router.patch("/tags/{tag_id}")
async def rename_user_tag(
    workspace_id: UUID, tag_id: UUID, data: NameRequest, user: ApiUser, db: Database
) -> OkView:
    await rename_tag(db, user, workspace_id, tag_id, data.name)
    return OkView()


@router.delete("/tags/{tag_id}")
async def delete_user_tag(workspace_id: UUID, tag_id: UUID, user: ApiUser, db: Database) -> OkView:
    await delete_tag(db, user, workspace_id, tag_id)
    return OkView()
