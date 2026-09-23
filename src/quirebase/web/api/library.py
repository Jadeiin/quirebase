from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from quirebase.access import Capability, resolve_workspace_context, role_has_capability
from quirebase.library import (
    DiscussionWorkspace,
    ItemMetadata,
    MetadataWorkspace,
    WorkspaceSection,
    add_discussion_message,
    add_tag_to_item,
    apply_bulk_item_action,
    apply_item_tag_selection,
    copy_item_to_workspace,
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
    BulkActionRequest,
    CitationView,
    CrossWorkspaceCopyRequest,
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

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["Library"])


@router.post("/items/bulk", response_model=OkView)
async def apply_item_bulk_action(
    workspace_id: str, data: BulkActionRequest, user: ApiUser, db: Database
) -> OkView:
    await apply_bulk_item_action(
        db,
        user,
        workspace_id=workspace_id,
        item_ids=data.item_ids,
        action=data.action,
        project_id=data.project_id,
        tag_name=data.tag_name,
        confirm_delete=data.confirmation,
    )
    return OkView()


@router.get("/items", response_model=LibrarySearchView)
async def search_items(
    workspace_id: str,
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
        workspace_id,
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
)
async def create_library_item(
    workspace_id: str, metadata: ItemMetadata, user: ApiUser, db: Database
) -> WriteResult:
    result = await create_item(db, user, workspace_id, metadata)
    return WriteResult(id=result.item_id, version=result.version)


@router.get("/items/{item_id}", response_model=ItemDetailView)
async def get_library_item(
    workspace_id: str, item_id: str, user: ApiUser, db: Database
) -> ItemDetailView:
    workspace = await open_item_workspace(
        db, user, workspace_id, item_id, WorkspaceSection.metadata
    )
    if not isinstance(workspace, MetadataWorkspace):  # pragma: no cover
        raise TypeError("item metadata workspace mismatch")
    return item_detail_view(workspace)


@router.put("/items/{item_id}", response_model=WriteResult)
async def update_library_item(
    workspace_id: str, item_id: str, data: ItemUpdateRequest, user: ApiUser, db: Database
) -> WriteResult:
    result = await revise_item_metadata(
        db, user, workspace_id, item_id, data.expected_version, data.metadata
    )
    return WriteResult(id=result.item_id, version=result.version)


@router.post(
    "/items/{item_id}/copy",
    response_model=WriteResult,
    status_code=status.HTTP_201_CREATED,
)
async def copy_library_item(
    workspace_id: str,
    item_id: str,
    data: CrossWorkspaceCopyRequest,
    user: ApiUser,
    db: Database,
) -> WriteResult:
    copied = await copy_item_to_workspace(db, user, workspace_id, data.target_workspace_id, item_id)
    return WriteResult(id=copied.id, version=copied.version)


@router.get(
    "/items/{item_id}/citation",
    response_model=CitationView,
)
async def format_item_citation(
    workspace_id: str,
    item_id: str,
    user: ApiUser,
    db: Database,
    style: str = "apa",
    output: Annotated[str, Query(pattern="^(text|html)$")] = "text",
) -> CitationView:
    content, media_type = await get_item_citation_text_response(
        db, user, workspace_id, item_id, style_key=style, output=output
    )
    return CitationView(content=content, media_type=media_type)


@router.get("/tags", response_model=list[TagView])
async def list_tags(workspace_id: str, user: ApiUser, db: Database) -> list[TagView]:
    rows = await list_accessible_tags_with_counts(db, user, workspace_id)
    context = await resolve_workspace_context(db, user, workspace_id)
    can_manage = role_has_capability(context.role, Capability.tags_manage)
    return [
        TagView(
            id=tag.id,
            name=tag.name,
            accessible_item_count=count,
            can_manage=can_manage,
        )
        for tag, count in rows
    ]


@router.post("/items/{item_id}/tags", response_model=WriteResult)
async def add_item_tag(
    workspace_id: str, item_id: str, data: NameRequest, user: ApiUser, db: Database
) -> WriteResult:
    assignment = await add_tag_to_item(db, user, workspace_id, item_id, data.name)
    return WriteResult(id=assignment.tag_id)


@router.delete(
    "/items/{item_id}/tags/{tag_id}",
    response_model=OkView,
)
async def remove_item_tag(
    workspace_id: str, item_id: str, tag_id: str, user: ApiUser, db: Database
) -> OkView:
    await remove_tag_from_item(db, user, workspace_id, item_id, tag_id)
    return OkView()


@router.put("/items/{item_id}/tags", response_model=OkView)
async def set_item_tag_selection(
    workspace_id: str, item_id: str, data: TagSetRequest, user: ApiUser, db: Database
) -> OkView:
    await apply_item_tag_selection(
        db,
        user,
        workspace_id,
        item_id,
        remove_tag_ids=data.remove_tag_ids,
        tag_ids=data.add_tag_ids,
        new_names=data.new_names,
    )
    return OkView()


@router.get(
    "/items/{item_id}/discussions",
    response_model=list[DiscussionMessageView],
)
async def list_discussions(
    workspace_id: str, item_id: str, user: ApiUser, db: Database
) -> list[DiscussionMessageView]:
    workspace = await open_item_workspace(
        db, user, workspace_id, item_id, WorkspaceSection.discussion
    )
    if not isinstance(workspace, DiscussionWorkspace):  # pragma: no cover
        raise TypeError("item discussion workspace mismatch")
    return discussion_message_views(workspace)


@router.post(
    "/items/{item_id}/discussions",
    response_model=WriteResult,
    status_code=status.HTTP_201_CREATED,
)
async def create_discussion(
    workspace_id: str, item_id: str, data: DiscussionRequest, user: ApiUser, db: Database
) -> WriteResult:
    message = await add_discussion_message(db, user, workspace_id, item_id, data.body)
    return WriteResult(id=message.id)


@router.delete(
    "/items/{item_id}/discussions/{message_id}",
    response_model=OkView,
)
async def delete_discussion(
    workspace_id: str, item_id: str, message_id: str, user: ApiUser, db: Database
) -> OkView:
    await delete_discussion_message(db, user, workspace_id, item_id, message_id)
    return OkView()
