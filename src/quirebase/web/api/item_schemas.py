from __future__ import annotations

from pydantic import BaseModel, Field

from quirebase.models import ProjectParticipation
from quirebase.web.api.common import WorkspaceAuthorizationView
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


class ItemOverviewCountsView(BaseModel):
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


class ItemCopyTargetView(BaseModel):
    """A currently eligible copy destination; the command rechecks authority."""

    id: str
    name: str


class ItemOverviewView(BaseModel):
    item: ItemSearchView
    authorization: WorkspaceAuthorizationView
    counts: ItemOverviewCountsView
    tags: list[ItemTagView]
    identifiers: list[ItemIdentifierView]
    latest_revision: ItemLatestRevisionView | None = None
    thumbnail: ItemThumbnailView | None = None
    copy_targets: list[ItemCopyTargetView]


class ItemOrganizeProjectView(BaseModel):
    id: str
    name: str
    assigned: bool
    participation: ProjectParticipation
    is_participating: bool


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
    authorization: WorkspaceAuthorizationView
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
    editable: bool = Field(description="Whether the User may create Annotations in this Project.")


class PdfViewerView(BaseModel):
    item: ItemSearchView
    editable: bool = Field(description="Whether the User may create private Annotations.")
    annotation_author: str
    revision: PdfViewerRevisionView
    projects: list[PdfViewerProjectView]
