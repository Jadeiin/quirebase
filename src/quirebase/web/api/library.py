from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from quirebase.library import (
    DiscussionWorkspace,
    ItemMetadata,
    MetadataWorkspace,
    WorkspaceSection,
    add_discussion_message,
    add_tag_to_item,
    apply_item_tag_selection,
    create_item,
    delete_discussion_message,
    get_item_citation_text_response,
    list_accessible_tags_with_counts,
    open_item_workspace,
    remove_tag_from_item,
    revise_item_metadata,
    search_library,
)
from quirebase.web.api.common import OkView, WriteResult
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.library_schemas import (
    CitationView,
    DiscussionMessageView,
    DiscussionRequest,
    ItemDetailView,
    ItemUpdateRequest,
    LibrarySearchView,
    NameRequest,
    TagSetRequest,
    TagView,
    discussion_message_views,
    item_detail_view,
    item_search_view,
)

router = APIRouter(prefix="/api/v1", tags=["Library"])


@router.get("/items", response_model=LibrarySearchView, operation_id="library.search")
async def search_items(
    user: ApiUser,
    db: Database,
    query: str = "",
    tag: str = "",
    project: str = "",
    year: str = "",
    keyword: str = "",
    author: str = "",
    page: Annotated[int, Query(ge=1)] = 1,
) -> LibrarySearchView:
    per_page = 25
    items, total, _tags, _years = await search_library(
        db,
        user,
        q=query,
        tag=tag,
        project=project,
        year=year,
        keyword=keyword,
        author=author,
        page=page,
        per_page=per_page,
    )
    return LibrarySearchView(
        items=[item_search_view(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post(
    "/items",
    response_model=WriteResult,
    status_code=status.HTTP_201_CREATED,
    operation_id="library.create_item",
)
async def create_library_item(metadata: ItemMetadata, user: ApiUser, db: Database) -> WriteResult:
    result = await create_item(db, user, metadata)
    return WriteResult(id=result.item_id, version=result.version)


@router.get("/items/{item_id}", response_model=ItemDetailView, operation_id="library.get_item")
async def get_library_item(item_id: str, user: ApiUser, db: Database) -> ItemDetailView:
    workspace = await open_item_workspace(db, user, item_id, WorkspaceSection.metadata)
    if not isinstance(workspace, MetadataWorkspace):  # pragma: no cover
        raise TypeError("item metadata workspace mismatch")
    return item_detail_view(workspace)


@router.put("/items/{item_id}", response_model=WriteResult, operation_id="library.update_item")
async def update_library_item(
    item_id: str, data: ItemUpdateRequest, user: ApiUser, db: Database
) -> WriteResult:
    result = await revise_item_metadata(db, user, item_id, data.expected_version, data.metadata)
    return WriteResult(id=result.item_id, version=result.version)


@router.get(
    "/items/{item_id}/citation",
    response_model=CitationView,
    operation_id="citations.format_item",
)
async def format_item_citation(
    item_id: str,
    user: ApiUser,
    db: Database,
    style: str = "apa",
    output: Annotated[str, Query(pattern="^(text|html)$")] = "text",
) -> CitationView:
    content, media_type = await get_item_citation_text_response(
        db, user, item_id, style_key=style, output=output
    )
    return CitationView(content=content, media_type=media_type)


@router.get("/tags", response_model=list[TagView], operation_id="tags.list")
async def list_tags(user: ApiUser, db: Database) -> list[TagView]:
    rows = await list_accessible_tags_with_counts(db, user)
    return [TagView(id=tag.id, name=tag.name, accessible_item_count=count) for tag, count in rows]


@router.post("/items/{item_id}/tags", response_model=WriteResult, operation_id="tags.add_to_item")
async def add_item_tag(item_id: str, data: NameRequest, user: ApiUser, db: Database) -> WriteResult:
    assignment = await add_tag_to_item(db, user, item_id, data.name)
    return WriteResult(id=assignment.tag_id)


@router.delete(
    "/items/{item_id}/tags/{tag_id}",
    response_model=OkView,
    operation_id="tags.remove_from_item",
)
async def remove_item_tag(item_id: str, tag_id: str, user: ApiUser, db: Database) -> OkView:
    await remove_tag_from_item(db, user, item_id, tag_id)
    return OkView()


@router.put("/items/{item_id}/tags", response_model=OkView, operation_id="tags.set_for_item")
async def set_item_tag_selection(
    item_id: str, data: TagSetRequest, user: ApiUser, db: Database
) -> OkView:
    await apply_item_tag_selection(
        db,
        user,
        item_id,
        remove_tag_ids=data.remove_tag_ids,
        tag_ids=data.add_tag_ids,
        new_names=data.new_names,
    )
    return OkView()


@router.get(
    "/items/{item_id}/discussions",
    response_model=list[DiscussionMessageView],
    operation_id="discussions.list",
)
async def list_discussions(
    item_id: str, user: ApiUser, db: Database
) -> list[DiscussionMessageView]:
    workspace = await open_item_workspace(db, user, item_id, WorkspaceSection.discussion)
    if not isinstance(workspace, DiscussionWorkspace):  # pragma: no cover
        raise TypeError("item discussion workspace mismatch")
    return discussion_message_views(workspace)


@router.post(
    "/items/{item_id}/discussions",
    response_model=WriteResult,
    status_code=status.HTTP_201_CREATED,
    operation_id="discussions.add",
)
async def create_discussion(
    item_id: str, data: DiscussionRequest, user: ApiUser, db: Database
) -> WriteResult:
    message = await add_discussion_message(db, user, item_id, data.body)
    return WriteResult(id=message.id)


@router.delete(
    "/items/{item_id}/discussions/{message_id}",
    response_model=OkView,
    operation_id="discussions.delete",
)
async def delete_discussion(item_id: str, message_id: str, user: ApiUser, db: Database) -> OkView:
    await delete_discussion_message(db, user, item_id, message_id)
    return OkView()
