from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from advanced_alchemy.service import OffsetPagination
from fastapi import APIRouter, Depends, Query, status

from quirebase.access import (
    tag_decisions,
)
from quirebase.library import (
    ItemDiscussionData,
    ItemMetadata,
    ItemMetadataData,
    ItemSection,
    LibraryFacets,
    LibraryFilter,
    add_discussion_message,
    add_tag_to_item,
    apply_bulk_item_action,
    apply_item_tag_selection,
    copy_item_to_workspace,
    create_item,
    delete_discussion_message,
    get_item_citation_text_response,
    get_library_facets,
    list_accessible_tags_with_counts,
    moderate_discussion_message,
    open_item_section,
    remove_tag_from_item,
    revise_item_metadata,
    search_library,
)
from quirebase.models import ReferenceType
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

router = APIRouter(tags=["Library"])


def library_filters(
    query: str = "",
    tag: str = "",
    project: UUID | None = None,
    year: str = "",
    keyword: str = "",
    author: str = "",
    has_files: bool | None = None,
    reference_type: ReferenceType | None = None,
    keyword_exact: str | None = None,
    author_last_name: str | None = None,
    author_first_name: str | None = None,
    author_suffix: str | None = None,
) -> LibraryFilter:
    return LibraryFilter(
        q=query,
        tag=tag,
        project=project,
        year=year,
        keyword=keyword,
        author=author,
        has_files=has_files,
        reference_type=reference_type,
        keyword_exact=keyword_exact,
        author_last_name=author_last_name,
        author_first_name=author_first_name,
        author_suffix=author_suffix,
    )


LibraryFilters = Annotated[LibraryFilter, Depends(library_filters)]


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
        project_id=data.project_id,
        tag_name=data.tag_name,
        confirm_delete=data.confirmation,
    )
    return OkView()


@router.get("/items", response_model=LibrarySearchView)
async def search_items(
    workspace_id: UUID,
    user: ApiUser,
    db: Database,
    filters: LibraryFilters,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Literal["updated", "created", "title"] = "updated",
) -> LibrarySearchView:
    items, total = await search_library(
        db,
        user,
        workspace_id,
        q=filters.q,
        tag=filters.tag,
        project=filters.project,
        year=filters.year,
        keyword=filters.keyword,
        author=filters.author,
        limit=limit,
        offset=offset,
        sort=sort,
        has_files=filters.has_files,
        reference_type=filters.reference_type,
        keyword_exact=filters.keyword_exact,
        author_last_name=filters.author_last_name,
        author_first_name=filters.author_first_name,
        author_suffix=filters.author_suffix,
    )
    return LibrarySearchView(
        items=[item_search_view(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/items/facets", response_model=LibraryFacets)
async def get_item_facets(
    workspace_id: UUID,
    user: ApiUser,
    db: Database,
    filters: LibraryFilters,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> LibraryFacets:
    return await get_library_facets(db, user, workspace_id, filters, limit=limit)


@router.post(
    "/items",
    response_model=WriteResult,
    status_code=status.HTTP_201_CREATED,
)
async def create_library_item(
    workspace_id: UUID, metadata: ItemMetadata, user: ApiUser, db: Database
) -> WriteResult:
    result = await create_item(db, user, workspace_id, metadata)
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
    result = await revise_item_metadata(
        db, user, workspace_id, item_id, data.expected_version, data.metadata
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
    output: Annotated[str, Query(pattern="^(text|html)$")] = "text",
) -> CitationView:
    content, media_type = await get_item_citation_text_response(
        db, user, workspace_id, item_id, style_key=style, output=output
    )
    return CitationView(content=content, media_type=media_type)


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
