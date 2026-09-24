from __future__ import annotations

from contextlib import suppress

from fastapi import APIRouter

from quirebase.core.errors import ResourceNotFound, ValidationFailure
from quirebase.documents import (
    resolve_item_thumbnail,
)
from quirebase.library import (
    ItemOrganizationData,
    ItemOverviewData,
    ItemSection,
    delete_item,
    open_item_section,
    regenerate_bibtex_key,
    regenerate_item_tag_recommendation,
    rescan_pdf_doi,
    search_authors_typeahead,
    sync_metadata_from_upstream,
)
from quirebase.operations.settings import get_effective_settings_model
from quirebase.web.api.common import OkView, WriteResult
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.item_schemas import (
    DeleteConfirmationRequest,
    ItemOrganizeView,
    ItemOverviewView,
    MetadataSyncRequest,
)
from quirebase.web.api.library_schemas import AuthorSuggestionView, item_search_view
from quirebase.web.api.serialization import enum_value

router = APIRouter(tags=["Items"])


@router.get("/items/{item_id}/overview", response_model=ItemOverviewView)
async def item_overview(workspace_id: str, item_id: str, user: ApiUser, db: Database):
    view = await open_item_section(db, user, workspace_id, item_id, ItemSection.overview)
    if not isinstance(view, ItemOverviewData):  # pragma: no cover
        raise TypeError("item overview section mismatch")
    latest = view.revisions[0] if view.revisions else None
    thumbnail = None
    with suppress(ResourceNotFound):
        resolved = await resolve_item_thumbnail(db, user, workspace_id, item_id)
        thumbnail = {
            "source_kind": resolved.source_kind,
            "source_id": resolved.source_id,
        }
    return {
        "item": item_search_view(view.item),
        "allowed_actions": {"edit": view.can_edit, "delete": view.can_delete},
        "counts": {
            "revisions": view.revision_count,
            "attachments": view.attachment_count,
            "annotations": view.annotation_count,
            "discussion": view.message_count,
        },
        "tags": [{"id": tag.id, "name": tag.name} for tag in view.tags],
        "identifiers": [
            {"provider": identifier.provider, "value": identifier.value}
            for identifier in view.identifiers
        ],
        "latest_revision": (
            {
                "id": latest.id,
                "original_name": latest.original_name,
                "size": latest.size,
                "page_count": latest.page_count,
                "processing_state": enum_value(latest.processing_state),
            }
            if latest
            else None
        ),
        "thumbnail": thumbnail,
    }


@router.get("/items/{item_id}/organize", response_model=ItemOrganizeView)
async def item_organize(workspace_id: str, item_id: str, user: ApiUser, db: Database):

    view = await open_item_section(db, user, workspace_id, item_id, ItemSection.organize)
    if not isinstance(view, ItemOrganizationData):  # pragma: no cover
        raise TypeError("item organize section mismatch")
    matrix = view.tag_matrix
    return {
        "item": item_search_view(view.item),
        "allowed_actions": {"edit": view.can_edit, "delete": view.can_delete},
        "tags": [{"id": tag.id, "name": tag.name} for tag in view.tags],
        "projects": [
            {
                "id": project_option.project.id,
                "name": project_option.project.name,
                "assigned": project_option.project.id in view.assigned_project_ids,
            }
            for project_option in view.projects
        ],
        "tag_matrix": {
            "groups": [
                {
                    "letter": group.letter,
                    "tags": [{"id": tag.id, "name": tag.name} for tag in group.tags],
                    "names": list(group.names),
                }
                for group in matrix.groups
            ],
            "assigned_ids": sorted(matrix.assigned_ids),
            "recommended_ids": sorted(matrix.recommended_ids),
            "suggested_names": list(matrix.suggested_names),
            "suggested_single_words": list(matrix.suggested_single_words),
            "suggested_phrases": list(matrix.suggested_phrases),
            "recommendation_state": matrix.recommendation_state,
            "recommendation_error": matrix.recommendation_error,
        },
    }


@router.delete("/items/{item_id}", response_model=OkView)
async def delete_library_item(
    workspace_id: str,
    item_id: str,
    data: DeleteConfirmationRequest,
    user: ApiUser,
    db: Database,
) -> OkView:
    if data.confirmation != "delete":
        raise ValidationFailure("confirm deletion to continue")
    await delete_item(db, user, workspace_id, item_id)
    return OkView()


@router.post("/items/{item_id}/metadata/sync", response_model=OkView)
async def sync_item_metadata(
    workspace_id: str,
    item_id: str,
    data: MetadataSyncRequest,
    user: ApiUser,
    db: Database,
) -> OkView:
    await sync_metadata_from_upstream(
        db,
        user,
        workspace_id,
        item_id,
        data.expected_version,
        provider=data.provider,
        uid_value=data.uid,
        settings=await get_effective_settings_model(db),
    )
    return OkView()


@router.post("/items/{item_id}/doi/rescan", response_model=OkView)
async def rescan_item_doi(workspace_id: str, item_id: str, user: ApiUser, db: Database) -> OkView:
    await rescan_pdf_doi(db, user, workspace_id, item_id)
    return OkView()


@router.post("/items/{item_id}/citation-key/regenerate", response_model=OkView)
async def regenerate_item_citation_key(
    workspace_id: str, item_id: str, user: ApiUser, db: Database
) -> OkView:
    await regenerate_bibtex_key(db, user, workspace_id, item_id)
    return OkView()


@router.post("/items/{item_id}/tag-recommendations", response_model=WriteResult)
async def regenerate_tag_recommendations(
    workspace_id: str, item_id: str, user: ApiUser, db: Database
) -> WriteResult:
    workflow_id = await regenerate_item_tag_recommendation(db, user, workspace_id, item_id)
    return WriteResult(id=workflow_id)


@router.get("/authors", response_model=list[AuthorSuggestionView])
async def suggest_authors(workspace_id: str, user: ApiUser, db: Database, query: str = ""):
    return await search_authors_typeahead(db, user, workspace_id, query=query)
