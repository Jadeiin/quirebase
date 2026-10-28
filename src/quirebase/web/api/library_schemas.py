from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from advanced_alchemy.service import OffsetPagination
from pydantic import BaseModel, ConfigDict, Field, Json

from quirebase.access import WorkspaceContext, discussion_message_decisions
from quirebase.library import (
    AuthorFilter,
    BulkItemAction,
    ItemMetadataData,
    LibraryFilter,
    Work,
    item_summary,
)
from quirebase.models import MAX_CITATION_KEY_LENGTH
from quirebase.web.api.common import WorkspaceAuthorizationView, authorization_view


class LibrarySearchQuery(BaseModel):
    query: str = ""
    tag: UUID | None = None
    project: UUID | None = None
    year: str = ""
    keyword: str = ""
    author: str = ""
    has_files: bool | None = None
    has_tags: bool | None = None
    has_projects: bool | None = None
    reference_type: str | None = None
    keyword_exact: str | None = None
    authors: Json[tuple[AuthorFilter, ...]] = Field(
        # Validate the encoded default as well as user-supplied JSON.
        default="[]",
        validate_default=True,
        description="Match any selected Author. An empty first_name selects a single-field name; "
        "an omitted or null first_name matches any given name.",
    )
    publication_title: str | None = None
    import_batch: UUID | None = None
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    sort: Literal["updated", "created", "title", "published", "publication", "author"] = "updated"
    direction: Literal["asc", "desc"] | None = None

    def to_filters(self) -> LibraryFilter:
        return LibraryFilter(
            q=self.query,
            tag=self.tag,
            project=self.project,
            year=self.year,
            keyword=self.keyword,
            author=self.author,
            has_files=self.has_files,
            has_tags=self.has_tags,
            has_projects=self.has_projects,
            reference_type=self.reference_type,
            keyword_exact=self.keyword_exact,
            authors=self.authors,
            publication_title=self.publication_title,
            import_batch=self.import_batch,
        )


class ItemAuthorView(BaseModel):
    """An ordered record credit and its exact Library Search name values."""

    full_name: str
    last_name: str
    first_name: str | None


class ItemSearchView(BaseModel):
    id: UUID
    title_html: str
    authors: list[ItemAuthorView]
    publication_date: str | None
    publication_title: str | None
    doi: str | None
    version: int


LibrarySearchView = OffsetPagination[ItemSearchView]


class _BulkItemSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_ids: list[UUID] = Field(min_length=1)


class BulkAddProjectRequest(_BulkItemSelectionRequest):
    action: Literal[BulkItemAction.add_project]
    project_id: UUID


class BulkRemoveProjectRequest(_BulkItemSelectionRequest):
    action: Literal[BulkItemAction.remove_project]
    project_id: UUID


class BulkAddTagRequest(_BulkItemSelectionRequest):
    action: Literal[BulkItemAction.add_tag]
    tag_name: str = Field(min_length=1)


class BulkRemoveTagRequest(_BulkItemSelectionRequest):
    action: Literal[BulkItemAction.remove_tag]
    tag_id: UUID


class BulkDeleteItemsRequest(_BulkItemSelectionRequest):
    action: Literal[BulkItemAction.delete_items]


BulkActionRequest = Annotated[
    BulkAddProjectRequest
    | BulkRemoveProjectRequest
    | BulkAddTagRequest
    | BulkRemoveTagRequest
    | BulkDeleteItemsRequest,
    Field(discriminator="action"),
]


class ItemDetailView(BaseModel):
    id: UUID
    version: int
    metadata: Work
    citation_key: str | None


class TagView(BaseModel):
    id: UUID
    name: str
    accessible_item_count: int
    authorization: WorkspaceAuthorizationView


class DiscussionMessageView(BaseModel):
    id: UUID
    item_id: UUID | None = None
    project_id: UUID | None = None
    author_id: UUID
    author_username: str
    mine: bool
    body: str
    created_at: str
    updated_at: str
    authorization: WorkspaceAuthorizationView


class CitationView(BaseModel):
    content: str
    media_type: str


class AuthorSuggestionView(BaseModel):
    last_name: str
    first_name: str | None = None
    full_name: str


class CitationStyleItemView(BaseModel):
    key: str
    name: str
    scope: Literal["builtin", "custom"]


def item_search_view(item: Any) -> ItemSearchView:
    return ItemSearchView(**item_summary(item))


def item_detail_view(view: ItemMetadataData) -> ItemDetailView:
    item = view.item
    return ItemDetailView(
        id=item.id,
        version=item.version,
        metadata=view.metadata,
        citation_key=item.citation_key,
    )


def discussion_message_view(
    row: Any, context: WorkspaceContext, *, writable: bool = True
) -> DiscussionMessageView:
    relation = "own" if row.author_id == context.actor_id else "other"
    return DiscussionMessageView(
        id=row.id,
        item_id=row.item_id,
        project_id=row.project_id,
        author_id=row.author_id,
        author_username=row.author.username,
        mine=relation == "own",
        body=row.body,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
        authorization=authorization_view(
            discussion_message_decisions(context, row, writable=writable)
        ),
    )


def discussion_message_views(
    workspace: Any, context: WorkspaceContext
) -> list[DiscussionMessageView]:
    return [discussion_message_view(row, context) for row in workspace.messages]


class ItemUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    metadata: Work
    citation_key: str | None = Field(default=None, max_length=MAX_CITATION_KEY_LENGTH)


class ItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metadata: Work
    citation_key: str | None = Field(default=None, max_length=MAX_CITATION_KEY_LENGTH)


class CrossWorkspaceCopyRequest(BaseModel):
    target_workspace_id: UUID


class CrossWorkspaceCopyView(BaseModel):
    source_workspace_id: UUID
    source_item_id: UUID
    target_workspace_id: UUID
    target_item_id: UUID


class NameRequest(BaseModel):
    name: str = Field(max_length=240)


class TagSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    add_tag_ids: list[UUID] = Field(default_factory=list)
    remove_tag_ids: list[UUID] = Field(default_factory=list)
    new_names: list[str] = Field(default_factory=list)


class DiscussionRequest(BaseModel):
    body: str


class DiscussionModerationRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
