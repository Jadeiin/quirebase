from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from quirebase.core.timezones import as_utc
from quirebase.library import ItemMetadata


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


class BulkActionRequest(BaseModel):
    item_ids: list[str]
    action: str
    project_id: str = ""
    tag_name: str = ""
    confirmation: str = ""


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


class TagView(BaseModel):
    id: str
    name: str
    accessible_item_count: int
    can_manage: bool


class DiscussionMessageView(BaseModel):
    id: str
    item_id: str | None = None
    project_id: str | None = None
    author_id: str
    author_username: str
    body: str
    created_at: str
    updated_at: str


class CitationView(BaseModel):
    content: str
    media_type: str


class AuthorSuggestionView(BaseModel):
    id: str
    last_name: str
    first_name: str | None = None
    full_name: str


class CitationStyleItemView(BaseModel):
    key: str
    name: str
    scope: Literal["builtin", "custom"]


class CitationStylesResponseView(BaseModel):
    styles: list[CitationStyleItemView]


def item_search_view(item: Any) -> ItemSearchView:
    return ItemSearchView(
        id=item.id,
        title_html=item.title,
        authors=item.authors,
        publication_date=item.publication_date,
        publication_title=item.publication_title,
        doi=item.doi,
        version=item.version,
    )


def item_detail_view(view: Any) -> ItemDetailView:
    item = view.item
    return ItemDetailView(
        **item_search_view(item).model_dump(),
        metadata=view.metadata,
        abstract_html=item.abstract,
        editors=[
            ContributorView(
                first_name=row.author.first_name,
                last_name=row.author.last_name,
                is_corresponding=row.is_corresponding,
            )
            for row in view.editors
        ],
        structured_authors=[
            ContributorView(
                first_name=row.author.first_name,
                last_name=row.author.last_name,
                is_corresponding=row.is_corresponding,
            )
            for row in view.authors
        ],
        reference_type=item.reference_type,
        volume=item.volume,
        issue=item.issue,
        pages=item.pages,
        keywords=item.keywords,
        urls=item.urls,
    )


def discussion_message_view(row: Any) -> DiscussionMessageView:
    return DiscussionMessageView(
        id=row.id,
        item_id=row.item_id,
        project_id=row.project_id,
        author_id=row.author_id,
        author_username=row.author.username,
        body=row.body,
        created_at=as_utc(row.created_at).isoformat(),
        updated_at=as_utc(row.updated_at).isoformat(),
    )


def discussion_message_views(workspace: Any) -> list[DiscussionMessageView]:
    return [discussion_message_view(row) for row in workspace.messages]


class ItemUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    metadata: ItemMetadata


class CrossWorkspaceCopyRequest(BaseModel):
    target_workspace_id: str = Field(min_length=1, max_length=36)


class CrossWorkspaceCopyView(BaseModel):
    source_workspace_id: str
    source_item_id: str
    target_workspace_id: str
    target_item_id: str


class NameRequest(BaseModel):
    name: str = Field(max_length=240)


class TagSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    add_tag_ids: list[str] = Field(default_factory=list)
    remove_tag_ids: list[str] = Field(default_factory=list)
    new_names: list[str] = Field(default_factory=list)


class DiscussionRequest(BaseModel):
    body: str
