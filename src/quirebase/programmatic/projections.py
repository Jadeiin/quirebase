from __future__ import annotations

from typing import Any

from quirebase.programmatic.views import (
    ContributorView,
    DiscussionMessageView,
    DocumentListView,
    FileView,
    ItemDetailView,
    ItemSearchView,
    ProjectDetailView,
    ProjectMemberView,
)


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


def item_detail_view(workspace: Any) -> ItemDetailView:
    item = workspace.item
    return ItemDetailView(
        **item_search_view(item).model_dump(),
        metadata=workspace.metadata,
        abstract_html=item.abstract,
        editors=[
            ContributorView(
                first_name=row.author.first_name,
                last_name=row.author.last_name,
                is_corresponding=row.is_corresponding,
            )
            for row in workspace.editors
        ],
        structured_authors=[
            ContributorView(
                first_name=row.author.first_name,
                last_name=row.author.last_name,
                is_corresponding=row.is_corresponding,
            )
            for row in workspace.authors
        ],
        reference_type=item.reference_type,
        volume=item.volume,
        issue=item.issue,
        pages=item.pages,
        keywords=item.keywords,
        urls=item.urls,
    )


def project_detail_view(workspace: Any) -> ProjectDetailView:
    return ProjectDetailView(
        id=workspace.project.id,
        name=workspace.project.name,
        role=workspace.membership.role,
        item_count=len(workspace.items),
        members=[
            ProjectMemberView(
                user_id=member.user.id,
                username=member.user.username,
                role=member.role,
            )
            for member in workspace.members
        ],
        items=[item_search_view(item) for item in workspace.items],
    )


def document_list_view(item_id: str, workspace: Any) -> DocumentListView:
    revisions = [
        FileView(
            id=row.id,
            kind="revision",
            original_name=row.original_name,
            mime_type=row.mime_type,
            size=row.size,
            sha256=row.sha256,
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
            sha256=row.sha256,
            created_at=row.created_at.isoformat(),
        )
        for row in workspace.attachments
    ]
    return DocumentListView(item_id=item_id, files=[*revisions, *attachments])


def discussion_message_views(workspace: Any) -> list[DiscussionMessageView]:
    return [
        DiscussionMessageView(
            id=row.id,
            item_id=row.item_id,
            author_id=row.author_id,
            author_username=row.author.username,
            body=row.body,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )
        for row in workspace.messages
    ]
