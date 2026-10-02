from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from quirebase.documents import (
    AnnotationCreate,
    AnnotationReplyCreate,
    AnnotationReplyUpdate,
    AnnotationScope,
    AnnotationUpdate,
    create_annotation_reply,
    create_document_annotation,
    delete_annotation_reply,
    delete_document_annotation,
    list_document_annotations,
    moderate_document_annotation,
    restore_annotation_reply,
    restore_document_annotation,
    update_annotation_reply,
    update_document_annotation,
)
from quirebase.web.api.annotation_schemas import (
    AnnotationListView,
    AnnotationModerationRequest,
    AnnotationProjectView,
    AnnotationReplyView,
    AnnotationRevisionView,
    AnnotationView,
)
from quirebase.web.api.common import OkView
from quirebase.web.api.dependencies import ApiUser, Database

router = APIRouter(tags=["Annotations"])


@router.get("/items/{item_id}/annotations", response_model=AnnotationListView)
async def list_annotations(
    workspace_id: str,
    item_id: str,
    user: ApiUser,
    db: Database,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 50,
    revision_id: str | None = None,
    scope: AnnotationScope | None = None,
    project_id: Annotated[
        list[str] | None,
        Query(description="Repeat to select multiple readable Projects linked to this Item."),
    ] = None,
    pagination: Literal["page", "cursor"] = "page",
    cursor: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
) -> AnnotationListView:
    """List authorized Annotations across revisions and sources.

    With no filters, return all visible sources. Project selection also includes the caller's
    private Annotations unless scope=project; scope=private excludes Project Annotations.
    Revision and Project choices are independent of the applied filters.
    Use pagination=cursor to traverse by immutable ID, then pass next_cursor as cursor.
    Page mode orders by latest update; cursor mode avoids skips when content is edited or deleted.
    """
    result = await list_document_annotations(
        db,
        user,
        workspace_id,
        item_id,
        revision_id,
        page=page,
        per_page=per_page,
        scope=scope,
        project_ids=tuple(project_id) if project_id is not None else None,
        pagination=pagination,
        cursor=cursor,
    )
    return AnnotationListView(
        revisions=[
            AnnotationRevisionView(id=revision.id, original_name=revision.original_name)
            for revision in result.revisions
        ],
        projects=[
            AnnotationProjectView(id=project.id, name=project.name) for project in result.projects
        ],
        annotations=[AnnotationView.model_validate(row) for row in result.annotations],
        total=result.total,
        page=page,
        per_page=per_page,
        next_cursor=result.next_cursor,
    )


@router.post(
    "/items/{item_id}/annotations",
    response_model=AnnotationView,
    status_code=status.HTTP_201_CREATED,
)
async def create_annotation(
    workspace_id: str,
    item_id: str,
    data: AnnotationCreate,
    user: ApiUser,
    db: Database,
) -> AnnotationView:
    return AnnotationView.model_validate(
        await create_document_annotation(db, user, workspace_id, item_id, data)
    )


@router.patch(
    "/items/{item_id}/annotations/{annotation_id}",
    response_model=AnnotationView,
)
async def update_annotation(
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    data: AnnotationUpdate,
    user: ApiUser,
    db: Database,
) -> AnnotationView:
    return AnnotationView.model_validate(
        await update_document_annotation(db, user, workspace_id, item_id, annotation_id, data)
    )


@router.delete(
    "/items/{item_id}/annotations/{annotation_id}",
    response_model=OkView,
)
async def delete_annotation(
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    version: int,
    user: ApiUser,
    db: Database,
) -> OkView:
    await delete_document_annotation(db, user, workspace_id, item_id, annotation_id, version)
    return OkView()


@router.post("/items/{item_id}/annotations/{annotation_id}/restore", response_model=AnnotationView)
async def restore_annotation(
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    version: int,
    user: ApiUser,
    db: Database,
) -> AnnotationView:
    return AnnotationView.model_validate(
        await restore_document_annotation(db, user, workspace_id, item_id, annotation_id, version)
    )


@router.post(
    "/items/{item_id}/annotations/{annotation_id}/moderation",
    response_model=AnnotationView,
)
async def moderate_annotation(
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    data: AnnotationModerationRequest,
    user: ApiUser,
    db: Database,
) -> AnnotationView:
    return AnnotationView.model_validate(
        await moderate_document_annotation(
            db,
            user,
            workspace_id,
            item_id,
            annotation_id,
            data.action,
            data.version,
        )
    )


@router.post(
    "/items/{item_id}/annotations/{annotation_id}/replies",
    response_model=AnnotationReplyView,
    status_code=status.HTTP_201_CREATED,
)
async def create_reply(
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    data: AnnotationReplyCreate,
    user: ApiUser,
    db: Database,
) -> AnnotationReplyView:
    return AnnotationReplyView.model_validate(
        await create_annotation_reply(db, user, workspace_id, item_id, annotation_id, data)
    )


@router.patch(
    "/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}",
    response_model=AnnotationReplyView,
)
async def update_reply(
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    reply_id: str,
    data: AnnotationReplyUpdate,
    user: ApiUser,
    db: Database,
) -> AnnotationReplyView:
    return AnnotationReplyView.model_validate(
        await update_annotation_reply(
            db, user, workspace_id, item_id, annotation_id, reply_id, data
        )
    )


@router.delete(
    "/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}",
    response_model=OkView,
)
async def delete_reply(
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    reply_id: str,
    version: int,
    user: ApiUser,
    db: Database,
) -> OkView:
    await delete_annotation_reply(db, user, workspace_id, item_id, annotation_id, reply_id, version)
    return OkView()


@router.post(
    "/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}/restore",
    response_model=AnnotationReplyView,
)
async def restore_reply(
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    reply_id: str,
    version: int,
    user: ApiUser,
    db: Database,
) -> AnnotationReplyView:
    return AnnotationReplyView.model_validate(
        await restore_annotation_reply(
            db, user, workspace_id, item_id, annotation_id, reply_id, version
        )
    )
