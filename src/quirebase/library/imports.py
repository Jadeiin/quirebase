from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime  # ruff: ignore[typing-only-standard-library-import] - Pydantic resolves preview values
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from advanced_alchemy.types import FileObject
from inquiro.bibliography import (
    SUPPORTED_FORMATS,
    detect_bibliography_format,
    parse_bibliography_records,
)
from inquiro.identifiers import canonical_doi
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import load_only

from quirebase.access import ResourceAction, require_workspace_action
from quirebase.audit import record_event
from quirebase.core.config import Settings, get_settings
from quirebase.core.errors import (
    DomainError,
    ResourceNotFound,
    ResourceUnavailable,
    SizeLimitExceeded,
    UpstreamServiceError,
    ValidationFailure,
)
from quirebase.core.storage import ObjectSource, get_object_store
from quirebase.core.workflows import IMPORT_QUEUE, durable_operations, object_reservation_attributes
from quirebase.documents import delete_unreferenced_objects, enqueue_object_cleanup
from quirebase.documents.pdf import extract_doi
from quirebase.documents.revisions import (
    StagedPdf,
    attach_staged_pdf,
    stage_pdf,
)
from quirebase.library.providers import lookup_candidate
from quirebase.library.workflows import request_item_tag_recommendation
from quirebase.models import ImportBatch, ImportBatchStatus, User
from quirebase.search import search_index

from ._metadata import Work, metadata_write, validate_citation_key
from .identifiers import _create_items_from_candidates

if TYPE_CHECKING:
    from collections.abc import Sequence

    from inquiro import CandidateRecord
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


class BatchConflict(DomainError):
    pass


class ImportBatchUnavailable(ResourceUnavailable):
    """The requested Import Batch is missing from the authorized Workspace."""


@dataclass(frozen=True)
class ImportSource:
    original_name: str
    size: int | None


@dataclass(frozen=True)
class ImportCandidatePreview:
    metadata: Work
    source: ImportSource | None = None


@dataclass(frozen=True)
class ImportDiagnostic:
    message: str
    severity: Literal["warning", "error"] = "error"
    row: int | None = None
    filename: str | None = None
    code: str | None = None
    identifier: str | None = None


@dataclass(frozen=True)
class ImportBatchPreview:
    id: UUID
    file_format: str
    status: ImportBatchStatus
    workflow_id: str | None
    records: tuple[ImportCandidatePreview, ...]
    errors: tuple[ImportDiagnostic, ...]
    created_at: datetime
    committed_item_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class ImportBatchSummary:
    id: UUID
    file_format: str
    status: ImportBatchStatus
    created_at: datetime
    record_count: int
    diagnostic_count: int


async def list_import_batches(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    *,
    view: Literal["pending", "completed"] = "pending",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[ImportBatchSummary], int]:
    """List retained previews and receipts without materializing candidate payloads."""
    await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    if view not in {"pending", "completed"} or not 1 <= limit <= 100 or offset < 0:
        raise ValidationFailure("invalid import pagination")
    predicate = (
        ImportBatch.status == ImportBatchStatus.committed
        if view == "completed"
        else ImportBatch.status != ImportBatchStatus.committed
    )
    scope = (ImportBatch.workspace_id == workspace_id, predicate)
    total = await db.scalar(select(func.count()).select_from(ImportBatch).where(*scope)) or 0
    length = (
        func.jsonb_array_length
        if db.get_bind().dialect.name == "postgresql"
        else func.json_array_length
    )
    rows = await db.execute(
        select(
            ImportBatch.id,
            ImportBatch.file_format,
            ImportBatch.status,
            ImportBatch.created_at,
            case(
                (
                    ImportBatch.status == ImportBatchStatus.committed,
                    length(ImportBatch.committed_item_ids),
                ),
                else_=length(ImportBatch.records),
            ),
            length(ImportBatch.errors),
        )
        .where(*scope)
        .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [ImportBatchSummary(*row) for row in rows], total


def _committed_item_ids(batch: ImportBatch) -> list[UUID]:
    if batch.status != "committed":
        return []
    committed_ids = batch.committed_item_ids or []
    if not isinstance(committed_ids, list) or not all(
        isinstance(item_id, str) for item_id in committed_ids
    ):
        raise BatchConflict("the committed batch has invalid results")
    try:
        return [UUID(item_id) for item_id in committed_ids]
    except ValueError as error:
        raise BatchConflict("the committed batch has invalid results") from error


def _import_batch_preview(batch: ImportBatch, actor_id: UUID) -> ImportBatchPreview:
    """Keep staging joins and actor-only workflow identities inside Library."""
    sources = {file.metadata["source_id"]: file for file in batch.staged_files}
    records = batch.records if batch.status in {"ready", "committed"} else []
    previews = []
    for record in records:
        source = sources.get(record.get("_source_id"))
        metadata = Work.model_validate(record["work"])
        previews.append(
            ImportCandidatePreview(
                metadata=metadata,
                source=ImportSource(source.metadata["original_name"], source.size)
                if source is not None
                else None,
            )
        )
    return ImportBatchPreview(
        id=batch.id,
        file_format=batch.file_format,
        status=ImportBatchStatus(batch.status),
        workflow_id=batch.workflow_id if batch.actor_id == actor_id else None,
        records=tuple(previews),
        errors=tuple(ImportDiagnostic(**error) for error in batch.errors),
        created_at=batch.created_at,
        committed_item_ids=tuple(_committed_item_ids(batch)),
    )


MAX_PDF_IMPORT_FILES = 50
MAX_IDENTIFIER_IMPORT_ENTRIES = 50
_WORKFLOW_NOT_LOOKED_UP = object()


def _consume_current_cancellation() -> None:
    task = asyncio.current_task()
    if task is not None:
        task.uncancel()


async def _finish_cleanup_despite_cancellation(task: asyncio.Task[None]) -> None:
    while True:
        try:
            await asyncio.shield(task)
            return
        except asyncio.CancelledError:
            _consume_current_cancellation()


def _pdf_import_inputs(files: list[FileObject]) -> list[dict]:
    """Snapshot batch-owned file descriptors as serializable durable inputs."""
    return [
        {
            "_row": file.metadata["row"],
            "_source_id": file.metadata["source_id"],
            "_pdf": {
                "object_key": file.path,
                "size": file.size,
                "original_name": file.metadata["original_name"],
            },
        }
        for file in files
    ]


async def stage_import_batch(
    db: AsyncSession, user: User, workspace_id: UUID, file_bytes: bytes, file_format: str = "auto"
) -> ImportBatchPreview:
    await require_workspace_action(db, user, workspace_id, ResourceAction.item_create)
    if file_format not in {"auto", *SUPPORTED_FORMATS}:
        raise ValidationFailure("format must be auto, bibtex, ris, csl-json, or commonmeta")
    if len(file_bytes) > 5 * 1024 * 1024:
        raise SizeLimitExceeded("bibliography files are limited to 5 MiB")
    try:
        contents = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValidationFailure("bibliography must be UTF-8") from error
    if file_format == "auto":
        try:
            file_format = detect_bibliography_format(contents)
        except ValueError as error:
            raise ValidationFailure(str(error)) from error
    typed_records, errors = parse_bibliography_records(contents, file_format)
    records = []
    for record in typed_records:
        try:
            values = metadata_write(record.work)
            records.append({**values, "citation_key": validate_citation_key(record.citation_key)})
        except ValidationFailure as error:
            errors.append({
                "row": record.row,
                "severity": "error",
                "code": "invalid_item",
                "message": str(error),
            })
    batch = ImportBatch(
        workspace_id=workspace_id,
        actor_id=user.id,
        file_format=file_format,
        records=records,
        errors=errors,
    )
    db.add(batch)
    await db.flush()
    await db.commit()
    return _import_batch_preview(batch, user.id)


async def stage_identifiers_import_batch(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    identifiers: Sequence[str],
    provider: str = "auto",
    settings: Settings | None = None,
) -> ImportBatchPreview:
    """Look up a bounded batch, retaining successful siblings in input order."""
    from quirebase.operations.settings import get_effective_settings_model

    await require_workspace_action(db, user, workspace_id, ResourceAction.item_create)
    if not identifiers or len(identifiers) > MAX_IDENTIFIER_IMPORT_ENTRIES:
        raise ValidationFailure(
            f"an identifier import batch requires 1 to {MAX_IDENTIFIER_IMPORT_ENTRIES} entries"
        )
    if any(not value.strip() or len(value) > 500 for value in identifiers):
        raise ValidationFailure("each identifier must contain 1 to 500 characters")
    user_id = user.id
    effective_settings = settings or await get_effective_settings_model(db)
    await db.rollback()
    semaphore = asyncio.Semaphore(3)

    async def lookup(
        value: str,
    ) -> CandidateRecord | ValidationFailure | ResourceNotFound | UpstreamServiceError:
        async with semaphore:
            try:
                return await lookup_candidate(value.strip(), provider, effective_settings)
            except (ValidationFailure, ResourceNotFound, UpstreamServiceError) as error:
                return error

    # TaskGroup cancels and joins outstanding requests on cancellation or an unexpected
    # failure. No database session is shared with the concurrent Provider requests.
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(lookup(value)) for value in identifiers]
    reloaded_user = await db.get(User, user_id)
    if reloaded_user is None or not reloaded_user.active:
        raise ResourceUnavailable("user not available")
    await require_workspace_action(db, reloaded_user, workspace_id, ResourceAction.item_create)
    records, errors, providers = [], [], []
    for row, (value, task) in enumerate(zip(identifiers, tasks, strict=True), 1):
        result = task.result()
        context = {"row": row, "identifier": value.strip()}
        if isinstance(result, (ValidationFailure, ResourceNotFound, UpstreamServiceError)):
            code = {
                ValidationFailure: "invalid_identifier",
                ResourceNotFound: "metadata_not_found",
                UpstreamServiceError: "provider_unavailable",
            }[type(result)]
            errors.append({**context, "code": code, "message": str(result)})
            continue
        try:
            records.append(metadata_write(result.work))
        except ValidationFailure as error:
            errors.append({**context, "code": "invalid_metadata", "message": str(error)})
            continue
        providers.append(result.provider)
        errors.extend(
            {**context, "severity": "warning", "code": "provider_limitations", "message": message}
            for message in result.diagnostics
        )
    batch = ImportBatch(
        workspace_id=workspace_id,
        actor_id=user_id,
        file_format="metadata",
        records=records,
        errors=errors,
    )
    db.add(batch)
    await db.flush()
    record_event(
        db,
        user_id,
        "metadata.import.preview",
        "import_batch",
        batch.id,
        detail={
            "requested": len(identifiers),
            "candidates": len(records),
            "providers": providers,
            "lookup_provider": provider,
        },
        workspace_id=workspace_id,
        authorization_resource_action=ResourceAction.item_create.value,
    )
    await db.commit()
    return _import_batch_preview(batch, user_id)


async def stage_pdf_import_batch(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    uploads: Sequence[tuple[ObjectSource, str]],
    *,
    max_bytes: int | None = None,
    settings: Settings | None = None,
) -> ImportBatchPreview:
    from quirebase.operations.settings import get_effective_setting

    await require_workspace_action(db, user, workspace_id, ResourceAction.item_create)
    if not uploads:
        raise ValidationFailure("at least one PDF is required")
    if len(uploads) > MAX_PDF_IMPORT_FILES:
        raise ValidationFailure(f"a PDF import batch is limited to {MAX_PDF_IMPORT_FILES} files")

    if max_bytes is None:
        max_bytes = (
            settings.max_pdf_bytes
            if settings is not None
            else await get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes)
        )
    user_id = user.id
    await db.rollback()
    staged_pdfs: list[StagedPdf] = []
    staged_files: list[FileObject] = []
    errors: list[dict] = []

    async def cleanup_staged_pdfs() -> None:
        await db.rollback()
        await delete_unreferenced_objects(db, {staged_pdf.object_key for staged_pdf in staged_pdfs})

    try:
        for row, (source, filename) in enumerate(uploads, start=1):
            try:
                staged = await stage_pdf(db, source, filename, max_bytes)
                staged_pdfs.append(staged)
                staged_files.append(
                    FileObject(
                        backend="documents",
                        filename=staged.object_key,
                        content_type="application/pdf",
                        size=staged.size,
                        checksum=staged.checksum,
                        metadata={
                            "row": row,
                            "source_id": str(uuid4()),
                            "original_name": staged.original_name,
                        },
                    )
                )
            except DomainError as error:
                errors.append({
                    "row": row,
                    "filename": filename,
                    "code": "invalid_pdf",
                    "message": str(error),
                })

        reloaded_user = await db.get(User, user_id)
        if reloaded_user is None or not reloaded_user.active:
            raise ResourceUnavailable("user not available")
        reloaded_user = (
            await require_workspace_action(
                db, reloaded_user, workspace_id, ResourceAction.item_create
            )
        ).actor
        batch = ImportBatch(
            workspace_id=workspace_id,
            actor_id=reloaded_user.id,
            file_format="pdf",
            records=[],
            staged_files=staged_files,
            errors=errors,
            status="pending",
        )
        db.add(batch)
        await db.flush()
        workflow_id = f"prepare-pdf-import:{batch.id}"
        batch.workflow_id = workflow_id
        await durable_operations().enqueue_in_transaction(
            db,
            "library.prepare_pdf_import",
            reloaded_user.id,
            workspace_id,
            batch.id,
            workflow_id,
            _pdf_import_inputs(staged_files),
            queue_name=IMPORT_QUEUE,
            workflow_id=workflow_id,
            attributes={
                "capability": "library",
                "operation": "prepare_pdf_import",
                "actor_id": reloaded_user.id,
                "workspace_id": workspace_id,
                "batch_id": batch.id,
                **object_reservation_attributes(staged.object_key for staged in staged_pdfs),
            },
        )
        record_event(
            db,
            reloaded_user.id,
            "pdf.import.preview.request",
            "import_batch",
            batch.id,
            detail={"files": len(uploads), "diagnostics": len(errors)},
            workspace_id=workspace_id,
            authorization_resource_action=ResourceAction.item_create.value,
        )
        await db.commit()
        return _import_batch_preview(batch, reloaded_user.id)
    except asyncio.CancelledError:
        _consume_current_cancellation()
        cleanup_task = asyncio.create_task(cleanup_staged_pdfs())
        await _finish_cleanup_despite_cancellation(cleanup_task)
        raise
    except Exception:
        await cleanup_staged_pdfs()
        raise


def _pdf_import_candidate_error(pending: dict, code: str, error: DomainError) -> dict:
    pdf = pending["_pdf"]
    return {
        "error": {
            "row": int(pending["_row"]),
            "filename": pdf["original_name"],
            "code": code,
            "message": str(error),
        },
        "object_key": pdf["object_key"],
    }


async def extract_pdf_import_doi(pending: dict) -> dict:
    """Materialize one staged PDF and extract its DOI without database access."""
    pdf = pending["_pdf"]
    try:
        async with get_object_store().materialize(pdf["object_key"]) as path:
            detected_doi = await asyncio.to_thread(extract_doi, path)
    except DomainError as error:
        return _pdf_import_candidate_error(pending, "invalid_pdf", error)
    if not detected_doi:
        return _pdf_import_candidate_error(
            pending,
            "missing_doi",
            ValidationFailure("no DOI was found in this PDF"),
        )
    return {
        "detected_doi": detected_doi,
        "normalized_doi": canonical_doi(detected_doi),
        "object_key": pdf["object_key"],
    }


async def check_pdf_import_eligibility(
    db: AsyncSession,
    batch_id: UUID,
    pending: dict,
) -> dict:
    """Recheck the batch actor and Workspace before Provider I/O."""
    pdf = pending["_pdf"]
    batch = await db.get(ImportBatch, batch_id)
    if batch is None or batch.status != "pending":
        return {"discarded": True, "object_key": pdf["object_key"]}
    user = await db.get(User, batch.actor_id)
    if user is None or not user.active:
        return {"discarded": True, "object_key": pdf["object_key"]}
    await require_workspace_action(db, user, batch.workspace_id, ResourceAction.item_create)
    return {"eligible": True, "object_key": pdf["object_key"]}


async def lookup_pdf_import_candidate(
    db: AsyncSession,
    batch_id: UUID,
    pending: dict,
    detected_doi: str,
) -> dict:
    """Retrieve metadata for one extracted DOI without repeating PDF parsing."""
    from quirebase.operations.settings import get_effective_settings_model

    pdf = pending["_pdf"]
    batch = await db.get(ImportBatch, batch_id)
    if batch is None or batch.status != "pending":
        return {"discarded": True, "object_key": pdf["object_key"]}
    user = await db.get(User, batch.actor_id)
    if user is None or not user.active:
        return {"discarded": True, "object_key": pdf["object_key"]}
    effective_settings = await get_effective_settings_model(db)
    await db.rollback()
    try:
        normalized_doi = canonical_doi(detected_doi)
        record = await lookup_candidate(detected_doi, "doi", effective_settings)
        candidate = metadata_write(record.work)
        candidate["_source_id"] = pending["_source_id"]
        return {
            "record": candidate,
            "normalized_doi": normalized_doi,
            "object_key": pdf["object_key"],
        }
    except UpstreamServiceError:
        # Keep transient provider failures exceptional so the enclosing DBOS
        # step can retry them instead of publishing a permanent diagnostic.
        raise
    except ValidationFailure as error:
        return _pdf_import_candidate_error(pending, "invalid_doi", error)
    except ResourceNotFound as error:
        return _pdf_import_candidate_error(pending, "metadata_not_found", error)
    except DomainError as error:
        return _pdf_import_candidate_error(pending, "invalid_pdf", error)


async def finalize_pdf_import_batch(
    db: AsyncSession,
    actor_id: UUID,
    workspace_id: UUID,
    batch_id: UUID,
    workflow_id: str,
    records: list[dict],
    errors: list[dict],
) -> bool:
    batch = await db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update())
    if (
        batch is None
        or batch.actor_id != actor_id
        or batch.workspace_id != workspace_id
        or batch.status != "pending"
        or batch.workflow_id != workflow_id
    ):
        return False
    owner = await db.get(User, actor_id)
    try:
        if owner is None:
            raise ResourceUnavailable("user not available")
        await require_workspace_action(db, owner, workspace_id, ResourceAction.item_create)
    except DomainError:
        # The failed batch still owns its staged PDFs. Reference-aware cleanup
        # must leave these retry inputs intact until retry or explicit discard.
        batch.errors = [
            *batch.errors,
            {
                "row": 0,
                "code": "authorization_revoked",
                "message": "Workspace authorization is no longer available",
            },
        ]
        batch.status = ImportBatchStatus.failed
        return False
    initial_errors = batch.errors
    retained_sources = {record["_source_id"] for record in records}
    batch.staged_files = [
        file for file in batch.staged_files if file.metadata["source_id"] in retained_sources
    ]
    batch.records = records
    batch.errors = [*initial_errors, *errors]
    batch.status = ImportBatchStatus.ready
    record_event(
        db,
        batch.actor_id,
        "pdf.import.preview",
        "import_batch",
        batch.id,
        detail={"candidates": len(records), "diagnostics": len(initial_errors) + len(errors)},
        workspace_id=workspace_id,
        authorization_resource_action=ResourceAction.item_create.value,
    )
    return True


async def get_import_batch_preview(
    db: AsyncSession, user: User, workspace_id: UUID, batch_id: UUID
) -> ImportBatchPreview:
    await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    observed = await db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id))
    if observed is None or observed.workspace_id != workspace_id:
        raise ImportBatchUnavailable("import batch not found")
    observed_workflow_id = observed.workflow_id
    workflow = None
    if observed.status == "pending" and observed.file_format == "pdf":
        workflow = (
            await durable_operations().get(observed.workflow_id) if observed.workflow_id else None
        )
    batch = await db.scalar(
        select(ImportBatch)
        .where(ImportBatch.id == batch_id)
        .execution_options(populate_existing=True)
        .with_for_update(key_share=True)
    )
    if batch is None or batch.workspace_id != workspace_id:
        raise ImportBatchUnavailable("import batch not found")
    if batch.workflow_id == observed_workflow_id and await _converge_pdf_import_batch_status(
        db, batch, workflow
    ):
        await db.commit()
    return _import_batch_preview(batch, user.id)


async def _converge_pdf_import_batch_status(
    db: AsyncSession, batch: ImportBatch, workflow=_WORKFLOW_NOT_LOOKED_UP
) -> bool:
    """Map a missing or terminal durable preparation back to the retryable business state."""
    if batch.file_format != "pdf" or batch.status != "pending":
        return False
    observed_workflow_id = batch.workflow_id
    if workflow is _WORKFLOW_NOT_LOOKED_UP:
        workflow = (
            await durable_operations().get(observed_workflow_id) if observed_workflow_id else None
        )
    if workflow is not None and not workflow.is_terminal:
        return False
    result = await db.execute(
        update(ImportBatch)
        .where(
            ImportBatch.id == batch.id,
            ImportBatch.status == "pending",
            ImportBatch.workflow_id == observed_workflow_id,
        )
        .values(status="failed")
        .execution_options(synchronize_session=False)
    )
    changed = getattr(result, "rowcount", 0) == 1
    await db.refresh(batch)
    return changed


async def retry_pdf_import_batch(
    db: AsyncSession, user: User, workspace_id: UUID, batch_id: UUID
) -> ImportBatchPreview:
    """Retry a failed PDF Import Batch without relinquishing its staged objects."""
    await require_workspace_action(db, user, workspace_id, ResourceAction.item_create)
    observed = await db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id))
    if observed is None or observed.workspace_id != workspace_id:
        raise ImportBatchUnavailable("import batch not found")
    observed_workflow_id = observed.workflow_id
    workflow = None
    if observed.file_format == "pdf" and observed.status == "pending":
        workflow = (
            await durable_operations().get(observed.workflow_id) if observed.workflow_id else None
        )
    batch = await db.scalar(
        # Confirmation/retry mutate the Import Batch root.  A full UPDATE lock
        # serializes concurrent callers before either can create child Items or
        # transition the batch status.
        select(ImportBatch)
        .where(ImportBatch.id == batch_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if batch is None or batch.workspace_id != workspace_id:
        raise ImportBatchUnavailable("import batch not found")
    if batch.workflow_id == observed_workflow_id:
        await _converge_pdf_import_batch_status(db, batch, workflow)
    if batch.file_format != "pdf" or batch.status != "failed":
        raise BatchConflict("only a failed PDF import batch can be retried")
    pending_records = _pdf_import_inputs(batch.staged_files)
    if not pending_records:
        raise BatchConflict("the failed import batch has no staged PDFs to retry")

    workflow_id = f"prepare-pdf-import:{batch.id}:{uuid4()}"
    # A retry is a new authorization boundary.  Keep the Import Batch root,
    # workflow arguments and workflow attributes bound to the same actor so a
    # Workspace editor can successfully retry another member's failed batch.
    batch.actor_id = user.id
    batch.status = ImportBatchStatus.pending
    batch.workflow_id = workflow_id
    batch.errors = [error for error in batch.errors if error.get("code") != "authorization_revoked"]
    await durable_operations().enqueue_in_transaction(
        db,
        "library.prepare_pdf_import",
        user.id,
        workspace_id,
        batch.id,
        workflow_id,
        pending_records,
        queue_name=IMPORT_QUEUE,
        workflow_id=workflow_id,
        attributes={
            "capability": "library",
            "operation": "prepare_pdf_import",
            "actor_id": user.id,
            "workspace_id": workspace_id,
            "batch_id": batch.id,
            **object_reservation_attributes(
                record["_pdf"]["object_key"] for record in pending_records
            ),
        },
    )
    record_event(
        db,
        user.id,
        "pdf.import.preview.retry",
        "import_batch",
        batch.id,
        workspace_id=workspace_id,
        authorization_resource_action=ResourceAction.item_create.value,
    )
    await db.commit()
    return _import_batch_preview(batch, user.id)


async def commit_import_batch(
    db: AsyncSession, user: User, workspace_id: UUID, batch_id: UUID
) -> ImportBatchPreview:
    # Lock the confirmer before Workspace authorization. Account deactivation
    # uses the same User-before-Workspace order, so it cannot deadlock a
    # confirmation while the Import Batch root is being committed.
    actor = await db.scalar(
        select(User).where(User.id == user.id, User.active.is_(True)).with_for_update(read=True)
    )
    if actor is None:
        raise ResourceUnavailable("user not available")
    await require_workspace_action(db, actor, workspace_id, ResourceAction.item_create)
    # Confirmation mutates the Import Batch root and creates child Items.  A
    # full UPDATE lock serializes concurrent confirmations before either caller
    # can observe ``ready`` and create duplicate Items.
    batch = await db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update())
    if batch is None or batch.workspace_id != workspace_id:
        raise ImportBatchUnavailable("import batch not found")
    if batch.status == "committed":
        receipt = _import_batch_preview(batch, actor.id)
        await db.commit()
        return receipt
    if batch.status != "ready":
        raise BatchConflict("the import batch is still being prepared")
    records = batch.records
    if not records:
        raise BatchConflict("the import batch has no candidate records")
    source_files = {file.metadata["source_id"]: file for file in batch.staged_files}
    candidates: list[dict] = []
    selected_files: list[FileObject | None] = []
    for record in records:
        candidate = dict(record)
        source_id = candidate.pop("_source_id", None)
        pdf = source_files.get(source_id) if source_id is not None else None
        if source_id is not None and (pdf is None or pdf.size is None):
            raise BatchConflict("the candidate has no staged source file")
        candidates.append(candidate)
        selected_files.append(pdf)
    items = await _create_items_from_candidates(db, workspace_id, actor.id, candidates)
    committed_item_ids: list[UUID] = []
    for item, pdf in zip(items, selected_files, strict=True):
        await request_item_tag_recommendation(
            db, item.id, workspace_id=workspace_id, actor_id=actor.id
        )
        if pdf is not None:
            await attach_staged_pdf(db, actor, item, pdf)
        await search_index(db).index_item(db, item.id)
        record_event(
            db,
            actor.id,
            "pdf.import" if pdf is not None else "bibliography.import",
            "item",
            item.id,
            detail={
                "format": batch.file_format,
                "filename": pdf.metadata["original_name"] if pdf else None,
            },
            workspace_id=workspace_id,
            authorization_resource_action=ResourceAction.item_create.value,
        )
        committed_item_ids.append(item.id)
    batch.committed_item_ids = [str(item_id) for item_id in committed_item_ids]
    # Transfer file ownership to File Revisions in the same confirmation transaction.
    batch.staged_files = []
    batch.records = []
    batch.errors = []
    batch.workflow_id = None
    batch.status = ImportBatchStatus.committed
    receipt = _import_batch_preview(batch, actor.id)
    await db.commit()
    return receipt


async def delete_import_batch(
    db: AsyncSession, user: User, workspace_id: UUID, batch_id: UUID
) -> None:
    await require_workspace_action(db, user, workspace_id, ResourceAction.item_create)
    batch = await db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update())
    if batch is None or batch.workspace_id != workspace_id:
        raise ImportBatchUnavailable("import batch not found")
    object_keys = {file.path for file in batch.staged_files}
    record_event(
        db,
        user.id,
        "import.batch.delete",
        "import_batch",
        batch.id,
        workspace_id=workspace_id,
        authorization_resource_action=ResourceAction.item_create.value,
    )
    await db.delete(batch)
    await enqueue_object_cleanup(
        db,
        object_keys,
        actor_id=user.id,
        workspace_id=workspace_id,
        operation="import_batch_delete",
        target_id=batch.id,
    )
    await db.commit()


async def purge_expired_import_batches(
    db: AsyncSession,
    *,
    before: datetime,
    limit: int = 500,
    after: UUID | None = None,
) -> tuple[int, UUID | None]:
    """Retire one bounded page, preserving active or indeterminate preparation.

    The scan cursor advances past protected batches so they cannot starve later
    pages. The caller owns the transaction and starts a fresh scan each cycle.
    Root locks serialize retirement with confirmation, retry and PDF publication.
    """
    query = (
        select(ImportBatch)
        .options(
            load_only(
                ImportBatch.id,
                ImportBatch.actor_id,
                ImportBatch.workspace_id,
                ImportBatch.file_format,
                ImportBatch.status,
                ImportBatch.workflow_id,
                ImportBatch.staged_files,
                ImportBatch.updated_at,
                raiseload=True,
            )
        )
        .where(ImportBatch.updated_at <= before)
    )
    if after is not None:
        query = query.where(ImportBatch.id > after)
    batches = list(
        await db.scalars(
            query
            .order_by(ImportBatch.id)
            .limit(limit)
            .execution_options(populate_existing=True)
            .with_for_update(skip_locked=True)
        )
    )
    removed = 0
    for batch in batches:
        if (
            batch.file_format == "pdf"
            and batch.status == ImportBatchStatus.pending
            and batch.workflow_id
        ):
            try:
                workflow = await durable_operations().get(batch.workflow_id)
            except Exception:
                logger.warning(
                    "Cannot determine Import Batch preparation status: %s",
                    batch.workflow_id,
                    exc_info=True,
                )
                continue
            if workflow is not None and not workflow.is_terminal:
                continue
        object_keys = {file.path for file in batch.staged_files}
        await db.delete(batch)
        await enqueue_object_cleanup(
            db,
            object_keys,
            actor_id=batch.actor_id,
            workspace_id=batch.workspace_id,
            operation="import_batch_expire",
            target_id=batch.id,
        )
        removed += 1
    await db.flush()
    return removed, batches[-1].id if batches else None


async def import_staging_object_keys(
    db: AsyncSession, *, workspace_id: UUID | None = None
) -> set[str]:
    """Retained PDF staging ownership, including ready and failed batches awaiting retry.

    Committed batches no longer own staged objects. This read participates in the caller's
    transaction and does not acquire aggregate locks or complete the transaction.
    """
    query = select(ImportBatch.staged_files).where(
        ImportBatch.file_format == "pdf", ImportBatch.status != "committed"
    )
    if workspace_id is not None:
        query = query.where(ImportBatch.workspace_id == workspace_id)
    return {file.path for files in await db.scalars(query) for file in files}
