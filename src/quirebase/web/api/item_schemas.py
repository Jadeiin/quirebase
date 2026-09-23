from __future__ import annotations

from pydantic import BaseModel, Field

from quirebase.web.api.library_schemas import ItemSearchView


class DeleteConfirmationRequest(BaseModel):
    confirmation: str


class MetadataSyncRequest(BaseModel):
    expected_version: int = Field(ge=1)
    provider: str
    uid: str


class RemoteRevisionRequest(BaseModel):
    source: str = Field(min_length=1, max_length=4000)


class RemoteAttachmentRequest(RemoteRevisionRequest):
    graphical_abstract: bool = False


class ItemWorkspacePermissionsView(BaseModel):
    edit: bool
    delete: bool


class ItemWorkspaceCountsView(BaseModel):
    revisions: int
    attachments: int
    annotations: int
    discussion: int


class ItemTagView(BaseModel):
    id: str
    name: str


class ItemIdentifierView(BaseModel):
    provider: str
    value: str


class ItemLatestRevisionView(BaseModel):
    id: str
    original_name: str
    size: int
    page_count: int | None = None
    processing_state: str


class ItemThumbnailView(BaseModel):
    source_kind: str
    source_id: str


class ItemWorkspaceView(BaseModel):
    item: ItemSearchView
    permissions: ItemWorkspacePermissionsView
    counts: ItemWorkspaceCountsView
    tags: list[ItemTagView]
    identifiers: list[ItemIdentifierView]
    latest_revision: ItemLatestRevisionView | None = None
    thumbnail: ItemThumbnailView | None = None


class ItemOrganizeProjectView(BaseModel):
    id: str
    name: str
    assigned: bool


class TagMatrixGroupView(BaseModel):
    letter: str
    tags: list[ItemTagView]
    names: list[str]


class TagMatrixView(BaseModel):
    groups: list[TagMatrixGroupView]
    assigned_ids: list[str]
    recommended_ids: list[str]
    suggested_names: list[str]
    suggested_single_words: list[str]
    suggested_phrases: list[str]
    recommendation_state: str
    recommendation_error: str | None = None


class ItemOrganizeView(BaseModel):
    item: ItemSearchView
    permissions: ItemWorkspacePermissionsView
    tags: list[ItemTagView]
    projects: list[ItemOrganizeProjectView]
    tag_matrix: TagMatrixView


class PdfViewerRevisionView(BaseModel):
    id: str
    original_name: str
    page_count: int | None = None
    processing_state: str
    page_geometry: list[list[float]]
    content_url: str


class PdfViewerProjectView(BaseModel):
    id: str
    name: str


class PdfViewerView(BaseModel):
    item: ItemSearchView
    editable: bool
    annotation_author: str
    revision: PdfViewerRevisionView
    projects: list[PdfViewerProjectView]
