from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status
from fastapi.responses import Response, StreamingResponse

from quirebase.library import (
    DEFAULT_CITATION_KEY_FORMULA,
    BibliographyExportOptions,
    apply_bulk_item_action,
    commit_import_batch,
    create_custom_citation_style,
    delete_custom_citation_style,
    delete_tag,
    discard_import_batch,
    download_selected_item_documents,
    export_accessible_bibliography,
    export_selected_bibliography,
    find_duplicates,
    get_dashboard_data,
    get_import_batch_preview,
    merge_tags,
    rename_tag,
    retry_pdf_import_batch,
    stage_identifier_import_batch,
    stage_import_batch,
    stage_pdf_import_batch,
)
from quirebase.operations.settings import get_effective_settings_model
from quirebase.web.api.common import OkView, WriteResult
from quirebase.web.api.content import BIBLIOGRAPHY_CONTENT_TYPES
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.library_schemas import NameRequest, item_search_view
from quirebase.web.api.serialization import enum_value
from quirebase.web.api.workspace_schemas import (
    BibliographyExportRequest,
    BulkActionRequest,
    CitationStyleCreateRequest,
    DashboardView,
    DocumentArchiveRequest,
    DuplicatesReviewView,
    IdentifierImportRequest,
    ImportBatchRetryView,
    ImportBatchView,
    TagMergeRequest,
)
from quirebase.web.responses import content_disposition
from quirebase.web.uploads import upload_chunks

router = APIRouter(prefix="/api/v1", tags=["HTTP API"])


def _import_batch_view(batch, records: list[dict], errors: list[dict]) -> dict:
    return {
        "id": batch.id,
        "file_format": batch.file_format,
        "status": batch.status,
        "workflow_id": batch.workflow_id,
        "records": records,
        "errors": errors,
        "created_at": batch.created_at,
    }


@router.get("/dashboard", response_model=DashboardView)
async def dashboard(user: ApiUser, db: Database):

    data = await get_dashboard_data(db, user)
    return {
        "new_items": [item_search_view(item) for item in data["new_items"]],
        "recent_items": [
            {"item": item_search_view(item), "last_read_at": last_read_at}
            for item, last_read_at in data["recent_items"]
        ],
        "projects": [
            {"id": project.id, "name": project.name, "visibility": enum_value(project.visibility)}
            for project in data["projects"]
        ],
        "session_count": len(data["sessions"]),
    }


@router.post("/items/bulk", response_model=OkView)
async def apply_item_bulk_action(data: BulkActionRequest, user: ApiUser, db: Database) -> OkView:
    await apply_bulk_item_action(
        db,
        user,
        item_ids=data.item_ids,
        action=data.action,
        project_id=data.project_id,
        tag_name=data.tag_name,
        confirm_delete=data.confirmation,
    )
    return OkView()


def _bibliography_options(data: BibliographyExportRequest) -> BibliographyExportOptions:
    return BibliographyExportOptions(
        include_abstract=data.include_abstract,
        preserve_case=data.preserve_case,
        include_identifiers=data.include_identifiers,
        include_custom_fields=data.include_custom_fields,
        encoding=data.encoding,
        journal_mode=data.journal_mode,
        doi_policy=data.doi_policy,
        url_policy=data.url_policy,
        excluded_fields=tuple(data.excluded_fields),
        sort_by=data.sort_by,
        citation_key_formula=data.citation_key_formula.strip() or DEFAULT_CITATION_KEY_FORMULA,
        citation_key_force_ascii=data.citation_key_force_ascii,
    )


@router.post(
    "/items/bibliography",
    response_class=Response,
    responses={200: {"content": BIBLIOGRAPHY_CONTENT_TYPES}},
)
async def export_item_selection(
    data: BibliographyExportRequest, user: ApiUser, db: Database
) -> Response:
    contents, media_type, filename = await export_selected_bibliography(
        db,
        user,
        data.item_ids,
        data.file_format,
        style_key=data.style,
        options=_bibliography_options(data),
    )
    return Response(
        contents,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.post(
    "/items/documents/archive",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "application/zip": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
async def download_item_selection(
    data: DocumentArchiveRequest, user: ApiUser, db: Database
) -> StreamingResponse:
    archive = await download_selected_item_documents(
        db,
        user,
        data.item_ids,
        include_annotations=data.include_annotations,
        include_supplements=data.include_supplements,
        timezone=data.timezone,
    )
    return StreamingResponse(
        archive.body,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition(archive.filename)},
    )


@router.get(
    "/bibliography",
    response_class=Response,
    responses={200: {"content": BIBLIOGRAPHY_CONTENT_TYPES}},
)
async def export_library_bibliography(
    user: ApiUser, db: Database, file_format: str, style: str = "apa"
) -> Response:
    contents, media_type, filename = await export_accessible_bibliography(
        db, user, file_format, style_key=style
    )
    return Response(
        contents,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.post(
    "/imports/bibliography",
    response_model=ImportBatchView,
    status_code=status.HTTP_201_CREATED,
)
async def stage_bibliography_import(
    user: ApiUser,
    db: Database,
    bibliography: Annotated[UploadFile, File()],
    file_format: Annotated[str, Form()],
):
    raw = await bibliography.read(5 * 1024 * 1024 + 1)
    return _import_batch_view(*(await stage_import_batch(db, user, raw, file_format)))


@router.post(
    "/imports/identifier",
    response_model=ImportBatchView,
    status_code=status.HTTP_201_CREATED,
)
async def stage_identifier_import(data: IdentifierImportRequest, user: ApiUser, db: Database):
    result = await stage_identifier_import_batch(
        db,
        user,
        data.identifier,
        data.provider,
        settings=await get_effective_settings_model(db),
    )
    return _import_batch_view(*result)


@router.post(
    "/imports/pdfs",
    response_model=ImportBatchView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def stage_pdf_import(user: ApiUser, db: Database, pdfs: Annotated[list[UploadFile], File()]):
    result = await stage_pdf_import_batch(
        db,
        user,
        [(upload_chunks(pdf), pdf.filename or "") for pdf in pdfs],
        settings=await get_effective_settings_model(db),
    )
    return _import_batch_view(*result)


@router.get("/imports/{batch_id}", response_model=ImportBatchView)
async def import_batch(batch_id: str, user: ApiUser, db: Database):
    return _import_batch_view(*(await get_import_batch_preview(db, user, batch_id)))


@router.post("/imports/{batch_id}/retry", response_model=ImportBatchRetryView)
async def retry_import_batch(batch_id: str, user: ApiUser, db: Database):
    batch = await retry_pdf_import_batch(db, user, batch_id)
    return {"id": batch.id, "status": batch.status, "workflow_id": batch.workflow_id}


@router.post("/imports/{batch_id}/commit", response_model=OkView)
async def commit_staged_import(batch_id: str, user: ApiUser, db: Database) -> OkView:
    await commit_import_batch(db, user, batch_id)
    return OkView()


@router.delete("/imports/{batch_id}", response_model=OkView)
async def discard_staged_import(batch_id: str, user: ApiUser, db: Database) -> OkView:
    await discard_import_batch(db, user, batch_id)
    return OkView()


@router.get("/duplicates", response_model=DuplicatesReviewView)
async def duplicate_items(user: ApiUser, db: Database, mode: str = ""):
    return {
        "groups": [
            [item_search_view(item) for item in group]
            for group in await find_duplicates(db, user, mode)
        ]
    }


@router.post("/citation-styles", response_model=WriteResult, status_code=status.HTTP_201_CREATED)
async def create_citation_style(
    data: CitationStyleCreateRequest, user: ApiUser, db: Database
) -> WriteResult:
    style = await create_custom_citation_style(db, user, data.name, data.csl)
    return WriteResult(id=style.id)


@router.delete("/citation-styles/{style_id}", response_model=OkView)
async def delete_citation_style(style_id: str, user: ApiUser, db: Database) -> OkView:
    await delete_custom_citation_style(db, user, style_id)
    return OkView()


@router.post("/tags/merge", response_model=OkView)
async def merge_user_tags(data: TagMergeRequest, user: ApiUser, db: Database) -> OkView:
    await merge_tags(db, user, data.source_tag_id, data.target_tag_id)
    return OkView()


@router.patch("/tags/{tag_id}", response_model=OkView)
async def rename_user_tag(tag_id: str, data: NameRequest, user: ApiUser, db: Database) -> OkView:
    await rename_tag(db, user, tag_id, data.name)
    return OkView()


@router.delete("/tags/{tag_id}", response_model=OkView)
async def delete_user_tag(tag_id: str, user: ApiUser, db: Database) -> OkView:
    await delete_tag(db, user, tag_id)
    return OkView()
