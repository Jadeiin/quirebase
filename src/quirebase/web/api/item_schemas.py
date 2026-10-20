from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from quirebase.models import ProjectParticipation
from quirebase.web.api.common import WorkspaceAuthorizationView
from quirebase.web.api.library_schemas import ItemDetailView, ItemSearchView


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
    id: UUID
    name: str


class ItemThumbnailView(BaseModel):
    source_kind: str
    source_id: UUID


class ItemCopyTargetView(BaseModel):
    """A currently eligible copy destination; the command rechecks authority."""

    id: UUID
    name: str


class ItemOverviewView(ItemDetailView):
    authorization: WorkspaceAuthorizationView
    counts: ItemOverviewCountsView
    tags: list[ItemTagView]
    latest_revision_id: UUID | None = None
    thumbnail: ItemThumbnailView | None = None
    copy_targets: list[ItemCopyTargetView]


class MetadataSourceProviderView(BaseModel):
    id: str
    name: str


class ItemMetadataSourceView(BaseModel):
    namespace: str
    value: str
    providers: list[MetadataSourceProviderView]


class ItemMetadataSourcesView(BaseModel):
    version: int
    sources: list[ItemMetadataSourceView]


class ItemOrganizeProjectView(BaseModel):
    id: UUID
    name: str
    assigned: bool
    participation: ProjectParticipation
    is_participating: bool


class TagMatrixGroupView(BaseModel):
    letter: str
    tags: list[ItemTagView]


class TagMatrixView(BaseModel):
    groups: list[TagMatrixGroupView]
    assigned_ids: list[UUID]
    recommended_ids: list[UUID]
    suggested_names: list[str]
    recommendation_state: str
    recommendation_error: str | None = None


class ItemOrganizeView(BaseModel):
    authorization: WorkspaceAuthorizationView
    projects: list[ItemOrganizeProjectView]
    tag_matrix: TagMatrixView


class PdfViewerRevisionView(BaseModel):
    id: UUID
    original_name: str
    page_count: int | None = None
    processing_state: str
    page_geometry: list[list[float]]
    content_url: str


class PdfViewerProjectView(BaseModel):
    id: UUID
    name: str
    editable: bool = Field(description="Whether the User may create Annotations in this Project.")


class PdfViewerView(BaseModel):
    item: ItemSearchView
    editable: bool = Field(description="Whether the User may create private Annotations.")
    annotation_author: str
    revision: PdfViewerRevisionView
    projects: list[PdfViewerProjectView]
