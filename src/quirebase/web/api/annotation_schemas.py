from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from quirebase.documents import AnnotationKind, AnnotationPayload, AnnotationScope


class FileView(BaseModel):
    id: str
    kind: Literal["revision", "attachment"]
    original_name: str
    mime_type: str
    size: int
    created_at: str
    page_count: int | None = None
    processing_state: str | None = None


class DocumentListView(BaseModel):
    item_id: str
    files: list[FileView]


class AnnotationReplyView(BaseModel):
    id: str
    annotation_id: str
    body: str
    version: int
    author_display_name: str
    mine: bool
    editable: bool
    created_at: str
    updated_at: str


class AnnotationView(BaseModel):
    id: str
    revision_id: str
    page_index: int
    kind: AnnotationKind
    scope: AnnotationScope
    project_id: str | None
    body: str | None
    selected_text: str | None
    payload: AnnotationPayload
    version: int
    author_display_name: str
    mine: bool
    editable: bool
    created_at: str
    updated_at: str
    replies: list[AnnotationReplyView]


def document_list_view(item_id: str, workspace: Any) -> DocumentListView:
    revisions = [
        FileView(
            id=row.id,
            kind="revision",
            original_name=row.original_name,
            mime_type=row.mime_type,
            size=row.size,
            created_at=row.created_at.isoformat(),
            page_count=row.page_count,
            processing_state=row.processing_state,
        )
        for row in workspace.revisions
    ]
    attachments = [
        FileView(
            id=row.id,
            kind="attachment",
            original_name=row.original_name,
            mime_type=row.mime_type,
            size=row.size,
            created_at=row.created_at.isoformat(),
        )
        for row in workspace.attachments
    ]
    return DocumentListView(item_id=item_id, files=[*revisions, *attachments])


class AnnotationReviewRevisionView(BaseModel):
    id: str
    original_name: str


class AnnotationReviewAnnotationView(AnnotationView):
    revision_name: str


class AnnotationReviewView(BaseModel):
    revisions: list[AnnotationReviewRevisionView]
    annotations: list[AnnotationReviewAnnotationView]
    total: int
    page: int
    per_page: int
