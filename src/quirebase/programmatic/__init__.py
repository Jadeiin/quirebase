"""Shared contracts and pure projections for programmatic inbound adapters."""

from quirebase.programmatic.projections import (
    discussion_message_views,
    document_list_view,
    item_detail_view,
    item_search_view,
    project_detail_view,
)
from quirebase.programmatic.views import (
    AnnotationView,
    CitationView,
    ContributorView,
    DiscussionMessageView,
    DocumentListView,
    FileView,
    ItemDetailView,
    ItemSearchView,
    LibrarySearchView,
    OkView,
    ProjectDetailView,
    ProjectMemberView,
    ProjectSummaryView,
    TagView,
    WriteResult,
)

__all__ = [
    "AnnotationView",
    "CitationView",
    "ContributorView",
    "DiscussionMessageView",
    "DocumentListView",
    "FileView",
    "ItemDetailView",
    "ItemSearchView",
    "LibrarySearchView",
    "OkView",
    "ProjectDetailView",
    "ProjectMemberView",
    "ProjectSummaryView",
    "TagView",
    "WriteResult",
    "discussion_message_views",
    "document_list_view",
    "item_detail_view",
    "item_search_view",
    "project_detail_view",
]
