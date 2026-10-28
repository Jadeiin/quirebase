from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from advanced_alchemy.service import OffsetPagination
from fastapi import APIRouter, Query, status

from quirebase.access import (
    tag_decisions,
)
from quirebase.library import (
    ItemDiscussionData,
    ItemMetadataData,
    ItemSection,
    LibraryFacets,
    add_discussion_message,
    add_tag_to_item,
    apply_bulk_item_action,
    apply_item_tag_selection,
    copy_item_to_workspace,
    create_item,
    delete_discussion_message,
    get_library_facets,
    get_work_schema,
    list_accessible_tags_with_counts,
    moderate_discussion_message,
    open_item_section,
    remove_tag_from_item,
    render_item_citation,
    revise_item_metadata,
    search_library,
)
from quirebase.web.api.common import OkView, WriteResult, authorization_view
from quirebase.web.api.dependencies import ApiUser, Database, WorkspaceAccess
from quirebase.web.api.library_schemas import (
    BulkActionRequest,
    CitationView,
    CrossWorkspaceCopyRequest,
    CrossWorkspaceCopyView,
    DiscussionMessageView,
    DiscussionModerationRequest,
    DiscussionRequest,
    ItemCreateRequest,
    ItemDetailView,
    ItemUpdateRequest,
    LibrarySearchQuery,
    LibrarySearchView,
    NameRequest,
    TagSetRequest,
    TagView,
    discussion_message_views,
    item_detail_view,
    item_search_view,
)

router = APIRouter(tags=["Library"])


@router.post("/items/bulk", response_model=OkView)
async def apply_item_bulk_action(
    workspace_id: UUID, data: BulkActionRequest, user: ApiUser, db: Database
) -> OkView:
    await apply_bulk_item_action(
        db,
        user,
        workspace_id=workspace_id,
        item_ids=data.item_ids,
        action=data.action,
        **data.model_dump(exclude={"item_ids", "action"}),
    )
    return OkView()


@router.get("/items", response_model=LibrarySearchView)
async def search_items(
    workspace_id: UUID,
    user: ApiUser,
    db: Database,
    data: Annotated[LibrarySearchQuery, Query()],
) -> LibrarySearchView:
    items, total = await search_library(
        db,
        user,
        workspace_id,
        data.to_filters(),
        limit=data.limit,
        offset=data.offset,
        sort=data.sort,
        direction=data.direction,
    )
    return LibrarySearchView(
        items=[item_search_view(item) for item in items],
        total=total,
        limit=data.limit,
        offset=data.offset,
    )


@router.get("/items/facets", response_model=LibraryFacets)
async def get_item_facets(
    workspace_id: UUID,
    user: ApiUser,
    db: Database,
    data: Annotated[LibrarySearchQuery, Query()],
) -> LibraryFacets:
    return await get_library_facets(
        db,
        user,
        workspace_id,
        data.to_filters(),
        limit=data.limit,
        offset=data.offset,
        sort=data.sort,
        direction=data.direction,
    )


@router.post(
    "/items",
    response_model=WriteResult,
    status_code=status.HTTP_201_CREATED,
)
async def create_library_item(
    workspace_id: UUID, data: ItemCreateRequest, user: ApiUser, db: Database
) -> WriteResult:
    result = await create_item(
        db, user, workspace_id, data.metadata, citation_key=data.citation_key
    )
    return WriteResult(id=result.item_id, version=result.version)


@router.get("/items/{item_id}", response_model=ItemDetailView)
async def get_library_item(
    workspace_id: UUID, item_id: UUID, context: WorkspaceAccess, db: Database
) -> ItemDetailView:
    view = await open_item_section(db, context, item_id, ItemSection.metadata)
    if not isinstance(view, ItemMetadataData):  # pragma: no cover
        raise TypeError("item metadata section mismatch")
    return item_detail_view(view)


@router.put("/items/{item_id}", response_model=WriteResult)
async def update_library_item(
    workspace_id: UUID, item_id: UUID, data: ItemUpdateRequest, user: ApiUser, db: Database
) -> WriteResult:
    key_write = (
        {"citation_key": data.citation_key} if "citation_key" in data.model_fields_set else {}
    )
    result = await revise_item_metadata(
        db,
        user,
        workspace_id,
        item_id,
        data.expected_version,
        data.metadata,
        **key_write,
    )
    return WriteResult(id=result.item_id, version=result.version)


@router.post(
    "/items/{item_id}/copy",
    response_model=CrossWorkspaceCopyView,
    status_code=status.HTTP_201_CREATED,
)
async def copy_library_item(
    workspace_id: UUID,
    item_id: UUID,
    data: CrossWorkspaceCopyRequest,
    user: ApiUser,
    db: Database,
) -> CrossWorkspaceCopyView:
    copied = await copy_item_to_workspace(db, user, workspace_id, data.target_workspace_id, item_id)
    return CrossWorkspaceCopyView(
        source_workspace_id=workspace_id,
        source_item_id=item_id,
        target_workspace_id=copied.workspace_id,
        target_item_id=copied.id,
    )


@router.get(
    "/items/{item_id}/citation",
    response_model=CitationView,
)
async def format_item_citation(
    workspace_id: UUID,
    item_id: UUID,
    user: ApiUser,
    db: Database,
    style: str = "apa",
    output: Literal["text", "html"] = "text",
) -> CitationView:
    citation = await render_item_citation(
        db, user, workspace_id, item_id, style_key=style, output=output
    )
    return CitationView(content=citation.content, media_type=citation.media_type)


@router.get("/tags", response_model=OffsetPagination[TagView])
async def list_tags(
    workspace_id: UUID,
    context: WorkspaceAccess,
    db: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: str = "",
    tag_id: UUID | None = None,
) -> OffsetPagination[TagView]:
    rows, total = await list_accessible_tags_with_counts(
        db, context, limit=limit, offset=offset, search=search, tag_id=tag_id
    )
    return OffsetPagination(
        items=[
            TagView(
                id=tag.id,
                name=tag.name,
                accessible_item_count=count,
                authorization=authorization_view(tag_decisions(context)),
            )
            for tag, count in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/items/{item_id}/tags", response_model=WriteResult)
async def add_item_tag(
    workspace_id: UUID, item_id: UUID, data: NameRequest, user: ApiUser, db: Database
) -> WriteResult:
    assignment = await add_tag_to_item(db, user, workspace_id, item_id, data.name)
    return WriteResult(id=assignment.tag_id)


@router.delete(
    "/items/{item_id}/tags/{tag_id}",
    response_model=OkView,
)
async def remove_item_tag(
    workspace_id: UUID, item_id: UUID, tag_id: UUID, user: ApiUser, db: Database
) -> OkView:
    await remove_tag_from_item(db, user, workspace_id, item_id, tag_id)
    return OkView()


@router.put("/items/{item_id}/tags", response_model=OkView)
async def set_item_tag_selection(
    workspace_id: UUID, item_id: UUID, data: TagSetRequest, user: ApiUser, db: Database
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
    workspace_id: UUID, item_id: UUID, context: WorkspaceAccess, db: Database
) -> list[DiscussionMessageView]:
    view = await open_item_section(db, context, item_id, ItemSection.discussion)
    if not isinstance(view, ItemDiscussionData):  # pragma: no cover
        raise TypeError("item discussion section mismatch")
    return discussion_message_views(view, context)


@router.post(
    "/items/{item_id}/discussions",
    response_model=WriteResult,
    status_code=status.HTTP_201_CREATED,
)
async def create_discussion(
    workspace_id: UUID, item_id: UUID, data: DiscussionRequest, user: ApiUser, db: Database
) -> WriteResult:
    message = await add_discussion_message(db, user, workspace_id, item_id, data.body)
    return WriteResult(id=message.id)


@router.delete(
    "/items/{item_id}/discussions/{message_id}",
    response_model=OkView,
)
async def delete_discussion(
    workspace_id: UUID, item_id: UUID, message_id: UUID, user: ApiUser, db: Database
) -> OkView:
    await delete_discussion_message(db, user, workspace_id, item_id, message_id)
    return OkView()


@router.post("/items/{item_id}/discussions/{message_id}/moderation", response_model=OkView)
async def moderate_discussion(
    workspace_id: UUID,
    item_id: UUID,
    message_id: UUID,
    data: DiscussionModerationRequest,
    user: ApiUser,
    db: Database,
) -> OkView:
    await moderate_discussion_message(db, user, workspace_id, item_id, message_id, data.reason)
    return OkView()


@router.get("/metadata/schema")
async def commonmeta_schema(context: WorkspaceAccess) -> dict:
    return get_work_schema()
