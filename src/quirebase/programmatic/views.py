from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from quirebase.documents import AnnotationPayload  # ruff: ignore[typing-only-first-party-import]
from quirebase.library import (  # ruff: ignore[typing-only-first-party-import]
    ItemMetadata,
)


class ItemSearchView(BaseModel):
    id: str
    title_html: str
    authors: str | None
    publication_date: str | None
    publication_title: str | None
    doi: str | None
    version: int


class LibrarySearchView(BaseModel):
    items: list[ItemSearchView]
    total: int
    page: int
    per_page: int


class ContributorView(BaseModel):
    first_name: str | None
    last_name: str
    is_corresponding: bool = False


class ItemDetailView(ItemSearchView):
    metadata: ItemMetadata
    abstract_html: str | None
    editors: list[ContributorView]
    structured_authors: list[ContributorView]
    reference_type: str | None
    volume: str | None
    issue: str | None
    pages: str | None
    keywords: str | None
    urls: str | None


class WriteResult(BaseModel):
    id: str
    version: int | None = None


class OkView(BaseModel):
    ok: bool = True


class ProjectSummaryView(BaseModel):
    id: str
    name: str
    role: str
    item_count: int


class ProjectMemberView(BaseModel):
    user_id: str
    username: str
    role: str


class ProjectDetailView(ProjectSummaryView):
    members: list[ProjectMemberView]
    items: list[ItemSearchView]


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
    kind: str
    scope: str
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
    replies: list[AnnotationReplyView] = Field(default_factory=list)


class TagView(BaseModel):
    id: str
    name: str
    accessible_item_count: int


class DiscussionMessageView(BaseModel):
    id: str
    item_id: str
    author_id: str
    author_username: str
    body: str
    created_at: str
    updated_at: str


class CitationView(BaseModel):
    content: str
    media_type: str
