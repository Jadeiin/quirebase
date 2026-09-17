from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status
from fastapi.responses import StreamingResponse

from quirebase.access.items import require_editable_item
from quirebase.core.config import get_settings
from quirebase.core.errors import ValidationFailure
from quirebase.documents import (
    acquire_remote_attachment,
    create_attachment,
    create_item_document_bundle,
    delete_attachment,
    delete_file_revision,
    get_attachment_file,
    get_pdf_viewer_data,
    store_pdf_revision,
)
from quirebase.library import (
    OrganizeWorkspace,
    SummaryWorkspace,
    WorkspaceSection,
    acquire_remote_pdf,
    delete_item,
    open_item_workspace,
    regenerate_bibtex_key,
    regenerate_item_tag_recommendation,
    rescan_pdf_doi,
    search_authors_typeahead,
    sync_metadata_from_upstream,
)
from quirebase.models import AttachmentRole
from quirebase.operations.settings import get_effective_setting, get_effective_settings_model
from quirebase.web.api.common import OkView, WriteResult
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.item_schemas import (
    DeleteConfirmationRequest,
    ItemOrganizeView,
    ItemWorkspaceView,
    MetadataSyncRequest,
    PdfViewerView,
    RemoteAttachmentRequest,
    RemoteRevisionRequest,
)
from quirebase.web.api.library_schemas import AuthorSuggestionView, item_search_view
from quirebase.web.api.serialization import enum_value
from quirebase.web.responses import content_disposition
from quirebase.web.uploads import upload_chunks

router = APIRouter(prefix="/api/v1", tags=["HTTP API"])


@router.get("/items/{item_id}/workspace", response_model=ItemWorkspaceView)
async def item_workspace(item_id: str, user: ApiUser, db: Database):
    workspace = await open_item_workspace(db, user, item_id, WorkspaceSection.summary)
    if not isinstance(workspace, SummaryWorkspace):  # pragma: no cover
        raise TypeError("item summary workspace mismatch")
    latest = workspace.revisions[0] if workspace.revisions else None
    return {
        "item": item_search_view(workspace.item),
        "permissions": {"edit": workspace.can_edit, "delete": workspace.can_delete},
        "counts": {
            "revisions": workspace.revision_count,
            "attachments": workspace.attachment_count,
            "annotations": workspace.annotation_count,
            "discussion": workspace.message_count,
        },
        "tags": [{"id": tag.id, "name": tag.name} for tag in workspace.tags],
        "owner": {"id": workspace.item_owner.id, "username": workspace.item_owner.username},
        "identifiers": [
            {"provider": identifier.provider, "value": identifier.value}
            for identifier in workspace.identifiers
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
    }


@router.get("/items/{item_id}/organize", response_model=ItemOrganizeView)
async def item_organize_workspace(item_id: str, user: ApiUser, db: Database):

    workspace = await open_item_workspace(db, user, item_id, WorkspaceSection.organize)
    if not isinstance(workspace, OrganizeWorkspace):  # pragma: no cover
        raise TypeError("item organize workspace mismatch")
    matrix = workspace.tag_matrix
    return {
        "item": item_search_view(workspace.item),
        "permissions": {"edit": workspace.can_edit, "delete": workspace.can_delete},
        "tags": [{"id": tag.id, "name": tag.name} for tag in workspace.tags],
        "projects": [
            {
                "id": membership.project.id,
                "name": membership.project.name,
                "role": enum_value(membership.role),
                "assigned": membership.project.id in workspace.assigned_project_ids,
            }
            for membership in workspace.memberships
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
    item_id: str, data: DeleteConfirmationRequest, user: ApiUser, db: Database
) -> OkView:
    if data.confirmation != "delete":
        raise ValidationFailure("confirm deletion to continue")
    await delete_item(db, user, item_id)
    return OkView()


@router.post("/items/{item_id}/metadata/sync", response_model=OkView)
async def sync_item_metadata(
    item_id: str, data: MetadataSyncRequest, user: ApiUser, db: Database
) -> OkView:
    await sync_metadata_from_upstream(
        db,
        user,
        item_id,
        data.expected_version,
        provider=data.provider,
        uid_value=data.uid,
        settings=await get_effective_settings_model(db),
    )
    return OkView()


@router.post("/items/{item_id}/doi/rescan", response_model=OkView)
async def rescan_item_doi(item_id: str, user: ApiUser, db: Database) -> OkView:
    await rescan_pdf_doi(db, user, item_id)
    return OkView()


@router.post("/items/{item_id}/citation-key/regenerate", response_model=OkView)
async def regenerate_item_citation_key(item_id: str, user: ApiUser, db: Database) -> OkView:
    await regenerate_bibtex_key(db, user, item_id)
    return OkView()


@router.post("/items/{item_id}/tag-recommendations", response_model=WriteResult)
async def regenerate_tag_recommendations(item_id: str, user: ApiUser, db: Database) -> WriteResult:
    workflow_id = await regenerate_item_tag_recommendation(db, user, item_id)
    return WriteResult(id=workflow_id)


@router.get("/authors", response_model=list[AuthorSuggestionView])
async def suggest_authors(user: ApiUser, db: Database, query: str = ""):
    del user
    return await search_authors_typeahead(db, query=query)


@router.get(
    "/items/{item_id}/archive",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/zip": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
async def download_item_archive(
    item_id: str,
    user: ApiUser,
    db: Database,
    revisions: str | None = None,
    include_annotations: bool = False,
    include_supplements: bool = False,
    timezone: str | None = None,
) -> StreamingResponse:
    revision_ids = (
        [value.strip() for value in revisions.split(",") if value.strip()] if revisions else None
    )
    bundle = await create_item_document_bundle(
        db,
        user,
        item_id,
        revision_ids=revision_ids,
        include_annotations=include_annotations,
        include_supplements=include_supplements,
        timezone=timezone,
    )
    return StreamingResponse(
        bundle.body,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition(bundle.filename)},
    )


@router.post(
    "/items/{item_id}/attachments", response_model=WriteResult, status_code=status.HTTP_202_ACCEPTED
)
async def upload_item_attachment(
    item_id: str,
    user: ApiUser,
    db: Database,
    attachment: Annotated[UploadFile, File()],
    graphical_abstract: Annotated[bool, Form()] = False,
) -> WriteResult:
    workflow = await create_attachment(
        db,
        user,
        item_id,
        upload_chunks(attachment),
        attachment.filename or "",
        attachment.content_type or "application/octet-stream",
        await get_effective_setting(
            db, "max_attachment_bytes", get_settings().max_attachment_bytes
        ),
        role=AttachmentRole.graphical_abstract if graphical_abstract else None,
    )
    return WriteResult(id=workflow.workflow_id)


@router.post(
    "/items/{item_id}/attachments/remote",
    response_model=WriteResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_remote_item_attachment(
    item_id: str, data: RemoteAttachmentRequest, user: ApiUser, db: Database
) -> WriteResult:
    max_bytes = await get_effective_setting(
        db, "max_attachment_bytes", get_settings().max_attachment_bytes
    )
    await require_editable_item(db, user, item_id)
    await db.rollback()
    async with acquire_remote_attachment(data.source, max_bytes) as attachment:
        workflow = await create_attachment(
            db,
            user,
            item_id,
            attachment.content,
            attachment.filename,
            attachment.media_type,
            max_bytes,
            role=AttachmentRole.graphical_abstract if data.graphical_abstract else None,
        )
    return WriteResult(id=workflow.workflow_id)


@router.get(
    "/items/{item_id}/attachments/{attachment_id}/content",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
async def download_item_attachment(
    item_id: str, attachment_id: str, user: ApiUser, db: Database
) -> StreamingResponse:
    response, original_name, media_type = await get_attachment_file(
        db, user, item_id, attachment_id
    )
    return StreamingResponse(
        response.body,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition(original_name)},
    )


@router.delete("/items/{item_id}/attachments/{attachment_id}", response_model=OkView)
async def delete_item_attachment(
    item_id: str, attachment_id: str, user: ApiUser, db: Database
) -> OkView:
    await delete_attachment(db, user, item_id, attachment_id)
    return OkView()


@router.post(
    "/items/{item_id}/revisions", response_model=WriteResult, status_code=status.HTTP_202_ACCEPTED
)
async def upload_item_pdf(
    item_id: str, user: ApiUser, db: Database, pdf: Annotated[UploadFile, File()]
) -> WriteResult:
    workflow = await store_pdf_revision(
        db,
        user,
        item_id,
        upload_chunks(pdf),
        pdf.filename or "",
        await get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes),
    )
    return WriteResult(id=workflow.workflow_id)


@router.post(
    "/items/{item_id}/revisions/remote",
    response_model=WriteResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_remote_item_pdf(
    item_id: str, data: RemoteRevisionRequest, user: ApiUser, db: Database
) -> WriteResult:
    settings = await get_effective_settings_model(db)
    max_bytes = await get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes)
    await require_editable_item(db, user, item_id)
    await db.rollback()
    async with acquire_remote_pdf(data.source, settings, max_bytes) as document:
        workflow = await store_pdf_revision(
            db, user, item_id, document.content, document.filename, max_bytes
        )
    return WriteResult(id=workflow.workflow_id)


@router.delete("/items/{item_id}/revisions/{revision_id}", response_model=OkView)
async def delete_item_pdf(item_id: str, revision_id: str, user: ApiUser, db: Database) -> OkView:
    await delete_file_revision(db, user, item_id, revision_id)
    return OkView()


@router.get("/items/{item_id}/revisions/{revision_id}/viewer", response_model=PdfViewerView)
async def pdf_viewer_configuration(item_id: str, revision_id: str, user: ApiUser, db: Database):
    data = await get_pdf_viewer_data(db, user, item_id, revision_id)
    revision = data["revision"]
    return {
        "item": item_search_view(data["item"]),
        # Reaching the viewer proves readable revision access. Annotation writes have
        # their own ownership/scope checks and intentionally do not require Item edits.
        "editable": True,
        "annotation_author": user.username,
        "revision": {
            "id": revision.id,
            "original_name": revision.original_name,
            "page_count": revision.page_count,
            "processing_state": enum_value(revision.processing_state),
            "page_geometry": json.loads(revision.page_geometry or "[]"),
            "content_url": f"/api/v1/items/{item_id}/revisions/{revision_id}/content",
        },
        "projects": [{"id": project.id, "name": project.name} for project in data["projects"]],
    }
