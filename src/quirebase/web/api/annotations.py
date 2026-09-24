from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from quirebase.documents import (
    AnnotationCreate,
    AnnotationReplyCreate,
    AnnotationReplyUpdate,
    AnnotationUpdate,
    create_annotation_reply,
    create_document_annotation,
    delete_annotation_reply,
    delete_document_annotation,
    list_document_annotations,
    moderate_document_annotation,
    restore_annotation_reply,
    restore_document_annotation,
    review_item_annotations,
    update_annotation_reply,
    update_document_annotation,
)
from quirebase.web.api.annotation_schemas import (
    AnnotationModerationRequest,
    AnnotationReplyView,
    AnnotationReviewAnnotationView,
    AnnotationReviewRevisionView,
    AnnotationReviewView,
    AnnotationView,
)
from quirebase.web.api.common import OkView
from quirebase.web.api.dependencies import ApiUser, Database

router = APIRouter(tags=["Annotations"])


@router.get("/items/{item_id}/annotations/review", response_model=AnnotationReviewView)
async def review_annotations(
    workspace_id: str,
    item_id: str,
    user: ApiUser,
    db: Database,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 50,
    revision_id: str | None = None,
) -> AnnotationReviewView:
    review = await review_item_annotations(
        db,
        user,
        workspace_id,
        item_id,
        page=page,
        per_page=per_page,
        revision_id=revision_id,
    )
    revision_names = {revision.id: revision.original_name for revision in review.revisions}
    return AnnotationReviewView(
        revisions=[
            AnnotationReviewRevisionView(id=revision.id, original_name=revision.original_name)
            for revision in review.revisions
        ],
        annotations=[
            AnnotationReviewAnnotationView.model_validate({
                **annotation,
                "revision_name": revision_names[annotation["revision_id"]],
            })
            for annotation in review.annotations
        ],
        total=review.total,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/items/{item_id}/annotations",
    response_model=list[AnnotationView],
)
async def list_annotations(
    workspace_id: str,
    item_id: str,
    revision_id: str,
    user: ApiUser,
    db: Database,
    project_id: str | None = None,
) -> list[AnnotationView]:
    return [
        AnnotationView.model_validate(row)
        for row in await list_document_annotations(
            db, user, workspace_id, item_id, revision_id, project_id
        )
    ]


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
