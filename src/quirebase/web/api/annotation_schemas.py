from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from quirebase.documents import AnnotationKind, AnnotationPayload, AnnotationScope
from quirebase.web.api.common import WorkspaceAuthorizationView


class FileView(BaseModel):
    id: UUID
    kind: Literal["revision", "attachment"]
    original_name: str
    mime_type: str
    size: int
    created_at: str
    page_count: int | None = None
    processing_state: str | None = None


class DocumentListView(BaseModel):
    item_id: UUID
    files: list[FileView]


class AnnotationReplyView(BaseModel):
    id: UUID
    annotation_id: UUID
    body: str
    version: int
    author_display_name: str
    mine: bool
    editable: bool
    created_at: str
    updated_at: str


class AnnotationView(BaseModel):
    id: UUID
    revision_id: UUID
    revision_name: str
    page_index: int
    kind: AnnotationKind
    scope: AnnotationScope
    project_id: UUID | None
    project_name: str | None
    body: str | None
    selected_text: str | None
    payload: AnnotationPayload
    version: int
    author_display_name: str
    mine: bool
    editable: bool
    authorization: WorkspaceAuthorizationView
    hidden_at: str | None = None
    archived_at: str | None = None
    locked_at: str | None = None
    moderated_by: UUID | None = None
    created_at: str
    updated_at: str
    replies: list[AnnotationReplyView]


class AnnotationModerationRequest(BaseModel):
    action: Literal["hide", "archive", "restore", "lock", "unlock", "delete"]
    version: int = Field(ge=1)


def document_list_view(item_id: UUID, item_files: Any) -> DocumentListView:
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
        for row in item_files.revisions
    ]
    attachments = [
        FileView(
            id=row.id,
            kind="attachment",
            original_name=row.file.metadata["original_name"],
            mime_type=row.file.content_type,
            size=row.file.size,
            created_at=row.created_at.isoformat(),
        )
        for row in item_files.attachments
    ]
    return DocumentListView(item_id=item_id, files=[*revisions, *attachments])


class AnnotationRevisionView(BaseModel):
    id: UUID
    original_name: str


class AnnotationProjectView(BaseModel):
    id: UUID
    name: str


class AnnotationListView(BaseModel):
    revisions: list[AnnotationRevisionView]
    projects: list[AnnotationProjectView]
    annotations: list[AnnotationView]
    total: int
    page: int
    per_page: int
    next_cursor: UUID | None = None
