from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING
from uuid import uuid4

from inquiro.bibliography import (
    SUPPORTED_FORMATS,
    BibliographyRecord,
    parse_bibliography_records,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from quirebase.access.items import require_accessible_items, visible_items_query
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
from quirebase.core.workflows import IMPORT_QUEUE, durable_operations
from quirebase.documents import enqueue_object_cleanup
from quirebase.documents.pdf import extract_doi
from quirebase.documents.revisions import (
    StagedPdf,
    attach_staged_pdf,
    delete_unreferenced_objects,
    stage_pdf,
)
from quirebase.library.activity import get_accessible_item_identifiers
from quirebase.library.citations import format_csl_export, format_standard_export
from quirebase.library.providers import candidate_record_values, lookup_candidate
from quirebase.models import ImportBatch, Item, ItemAuthor, PdfAnnotationMode, User
from quirebase.search import search_index

if TYPE_CHECKING:
    from collections.abc import Sequence

    from inquiro.bibliography import BibliographyExportOptions
    from sqlalchemy.ext.asyncio import AsyncSession


class BatchConflict(DomainError):
    pass


MAX_PDF_IMPORT_FILES = 50


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


def _pdf_object_keys(records_json: str) -> set[str]:
    try:
        records = json.loads(records_json)
    except (json.JSONDecodeError, TypeError):
        return set()
    return {
        pdf["object_key"]
        for record in records
        if isinstance(record, dict)
        and isinstance((pdf := record.get("_pdf")), dict)
        and isinstance(pdf.get("object_key"), str)
    }


def _record_to_item_payload(record: BibliographyRecord) -> dict[str, str | None]:
    """Serialize a parsed record into the Item-column dictionary stored on Import Batches."""
    return {
        "title": record.title or None,
        "abstract": record.abstract,
        "authors": "; ".join(person.storage_name() for person in record.authors) or None,
        "editors": "; ".join(person.storage_name() for person in record.editors) or None,
        "keywords": "; ".join(record.keywords) or None,
        "publication_date": record.publication_date,
        "publication_title": record.publication_title or record.book_title,
        "volume": record.volume,
        "issue": record.issue,
        "pages": record.pages,
        "publisher": record.publisher,
        "place_published": record.location,
        "doi": record.doi,
        "reference_type": record.reference_type,
        "bibtex_id": record.citation_key,
        "bibtex_type": record.bibtex_type,
        "urls": "\n".join(record.urls) or None,
        "identifiers": json.dumps(dict(record.identifiers), ensure_ascii=False)
        if record.identifiers
        else None,
        "custom_fields": json.dumps(dict(record.custom_fields), ensure_ascii=False)
        if record.custom_fields
        else None,
    }


async def stage_import_batch(
    db: AsyncSession, user: User, file_bytes: bytes, file_format: str
) -> tuple[ImportBatch, list[dict], list[dict]]:
    if file_format not in SUPPORTED_FORMATS:
        raise ValidationFailure("format must be bibtex, biblatex, ris, or endnote")
    if len(file_bytes) > 5 * 1024 * 1024:
        raise SizeLimitExceeded("bibliography files are limited to 5 MiB")
    try:
        contents = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValidationFailure("bibliography must be UTF-8") from error
    typed_records, errors = parse_bibliography_records(contents, file_format)
    records = [_record_to_item_payload(record) for record in typed_records]
    batch = ImportBatch(
        owner_id=user.id,
        file_format=file_format,
        records=json.dumps(records, ensure_ascii=False),
        errors=json.dumps(errors, ensure_ascii=False),
    )
    db.add(batch)
    await db.commit()
    return batch, records, errors


async def stage_identifier_import_batch(
    db: AsyncSession,
    user: User,
    identifier: str,
    provider: str = "auto",
    settings: Settings | None = None,
) -> tuple[ImportBatch, list[dict], list[dict]]:
    from quirebase.operations.settings import get_effective_settings_model

    user_id = user.id
    effective_settings = settings or await get_effective_settings_model(db)
    # Settings are a short read; release its transaction before external I/O.
    await db.rollback()
    record = await lookup_candidate(identifier, provider, effective_settings)
    reloaded_user = await db.get(User, user_id)
    if reloaded_user is None or not reloaded_user.active:
        raise ResourceUnavailable("user not available")
    user = reloaded_user
    rec_dict = candidate_record_values(record)
    batch = ImportBatch(
        owner_id=user.id,
        file_format=f"metadata:{record.identifier.provider}",
        records=json.dumps([rec_dict], ensure_ascii=False),
        errors="[]",
    )
    db.add(batch)
    await db.flush()
    record_event(
        db,
        user.id,
        "metadata.lookup",
        "import_batch",
        batch.id,
        detail={"provider": record.identifier.provider},
    )
    await db.commit()
    return batch, [rec_dict], []


async def stage_pdf_import_batch(
    db: AsyncSession,
    user: User,
    uploads: Sequence[tuple[ObjectSource, str]],
    *,
    max_bytes: int | None = None,
    settings: Settings | None = None,
    pdf_annotation_mode: PdfAnnotationMode | str = PdfAnnotationMode.preserve,
) -> tuple[ImportBatch, list[dict], list[dict]]:
    from quirebase.operations.settings import get_effective_setting

    if not uploads:
        raise ValidationFailure("at least one PDF is required")
    if len(uploads) > MAX_PDF_IMPORT_FILES:
        raise ValidationFailure(f"a PDF import batch is limited to {MAX_PDF_IMPORT_FILES} files")
    try:
        annotation_mode = PdfAnnotationMode(pdf_annotation_mode)
    except ValueError as error:
        raise ValidationFailure("pdf annotation mode must be preserve, strip, or import") from error

    if max_bytes is None:
        max_bytes = (
            settings.max_pdf_bytes
            if settings is not None
            else await get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes)
        )
    user_id = user.id
    await db.rollback()
    staged_pdfs: list[StagedPdf] = []
    pending_records: list[dict] = []
    errors: list[dict] = []

    async def cleanup_staged_pdfs() -> None:
        await db.rollback()
        for staged_pdf in staged_pdfs:
            await staged_pdf.release()
        await delete_unreferenced_objects(db, {staged_pdf.object_key for staged_pdf in staged_pdfs})

    try:
        for row, (source, filename) in enumerate(uploads, start=1):
            try:
                staged = await stage_pdf(db, source, filename, max_bytes)
                staged_pdfs.append(staged)
                pending_records.append({
                    "_row": row,
                    "_pdf": {
                        "object_key": staged.object_key,
                        "size": staged.size,
                        "original_name": staged.original_name,
                    },
                })
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
        batch = ImportBatch(
            owner_id=reloaded_user.id,
            file_format="pdf",
            records=json.dumps(pending_records, ensure_ascii=False),
            errors=json.dumps(errors, ensure_ascii=False),
            status="pending",
            pdf_annotation_mode=annotation_mode,
            max_pdf_bytes=max_bytes,
        )
        db.add(batch)
        await db.flush()
        workflow_id = f"prepare-pdf-import:{batch.id}"
        batch.workflow_id = workflow_id
        await durable_operations().enqueue_in_transaction(
            db,
            "library.prepare_pdf_import",
            batch.id,
            workflow_id,
            pending_records,
            annotation_mode.value,
            queue_name=IMPORT_QUEUE,
            workflow_id=workflow_id,
            attributes={
                "capability": "library",
                "operation": "prepare_pdf_import",
                "owner_id": reloaded_user.id,
                "batch_id": batch.id,
                "object_keys": [staged.object_key for staged in staged_pdfs],
                "pdf_annotation_mode": annotation_mode.value,
            },
        )
        record_event(
            db,
            reloaded_user.id,
            "pdf.import.preview.request",
            "import_batch",
            batch.id,
            detail={"files": len(uploads), "diagnostics": len(errors)},
        )
        await db.commit()
        for staged in staged_pdfs:
            await staged.release()
        return batch, [], errors
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
        "normalized_doi": detected_doi.casefold(),
        "object_key": pdf["object_key"],
    }


async def check_pdf_import_doi(
    db: AsyncSession,
    batch_id: str,
    pending: dict,
    detected_doi: str,
) -> dict:
    """Check one DOI against the current owner's accessible Items."""
    pdf = pending["_pdf"]
    batch = await db.get(ImportBatch, batch_id)
    if batch is None or batch.status != "pending":
        return {"discarded": True, "object_key": pdf["object_key"]}
    user = await db.get(User, batch.owner_id)
    if user is None or not user.active:
        return {"discarded": True, "object_key": pdf["object_key"]}
    normalized_doi = detected_doi.casefold()
    existing = await db.scalar(
        visible_items_query(user)
        .with_only_columns(Item.id)
        .where(func.lower(Item.doi) == normalized_doi)
        .limit(1)
    )
    if existing is not None:
        return _pdf_import_candidate_error(
            pending,
            "existing_doi",
            BatchConflict("an accessible Item already has this DOI"),
        )
    return {"eligible": True, "object_key": pdf["object_key"]}


async def lookup_pdf_import_candidate(
    db: AsyncSession,
    batch_id: str,
    pending: dict,
    detected_doi: str,
) -> dict:
    """Retrieve metadata for one extracted DOI without repeating PDF parsing."""
    from quirebase.operations.settings import get_effective_settings_model

    pdf = pending["_pdf"]
    batch = await db.get(ImportBatch, batch_id)
    if batch is None or batch.status != "pending":
        return {"discarded": True, "object_key": pdf["object_key"]}
    user = await db.get(User, batch.owner_id)
    if user is None or not user.active:
        return {"discarded": True, "object_key": pdf["object_key"]}
    effective_settings = await get_effective_settings_model(db)
    await db.rollback()
    try:
        normalized_doi = detected_doi.casefold()
        record = await lookup_candidate(detected_doi, "doi", effective_settings)
        candidate = candidate_record_values(record)
        candidate.setdefault("doi", detected_doi)
        candidate["_pdf"] = {**pdf, "detected_doi": detected_doi}
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


async def prepare_pdf_import_candidate(
    db: AsyncSession,
    batch_id: str,
    pending: dict,
) -> dict:
    """Prepare one candidate through the same seams used by the durable workflow."""
    extracted = await extract_pdf_import_doi(pending)
    detected_doi = extracted.get("detected_doi")
    if not isinstance(detected_doi, str):
        return extracted
    checked = await check_pdf_import_doi(db, batch_id, pending, detected_doi)
    if not checked.get("eligible"):
        return checked
    return await lookup_pdf_import_candidate(db, batch_id, pending, detected_doi)


async def finalize_pdf_import_batch(
    db: AsyncSession,
    batch_id: str,
    workflow_id: str,
    records: list[dict],
    errors: list[dict],
) -> bool:
    batch = await db.get(ImportBatch, batch_id)
    if batch is None or batch.status != "pending" or batch.workflow_id != workflow_id:
        return False
    owner = await db.get(User, batch.owner_id)
    if owner is None or not owner.active:
        batch.records = "[]"
        batch.errors = json.dumps([
            {"row": 0, "code": "user_unavailable", "message": "user not available"}
        ])
        batch.status = "failed"
        return False
    initial_errors = json.loads(batch.errors)
    batch.records = json.dumps(records, ensure_ascii=False)
    batch.errors = json.dumps([*initial_errors, *errors], ensure_ascii=False)
    batch.status = "ready"
    record_event(
        db,
        batch.owner_id,
        "pdf.import.preview",
        "import_batch",
        batch.id,
        detail={"candidates": len(records), "diagnostics": len(initial_errors) + len(errors)},
    )
    return True


async def _create_item_from_record(db: AsyncSession, user: User, record: dict) -> Item:
    from quirebase.library import create_item_from_metadata_record

    return await create_item_from_metadata_record(db, user, record)


async def get_import_batch_preview(
    db: AsyncSession, user: User, batch_id: str
) -> tuple[ImportBatch, list[dict], list[dict]]:
    batch = await db.get(ImportBatch, batch_id)
    if batch is None or batch.owner_id != user.id:
        raise ResourceUnavailable("import batch not found")
    if await _converge_pdf_import_batch_status(db, batch):
        await db.commit()
    records = json.loads(batch.records) if batch.status == "ready" else []
    return batch, records, json.loads(batch.errors)


async def _converge_pdf_import_batch_status(db: AsyncSession, batch: ImportBatch) -> bool:
    """Map a missing or terminal durable preparation back to the retryable business state."""
    if batch.file_format != "pdf" or batch.status != "pending":
        return False
    observed_workflow_id = batch.workflow_id
    workflow = (
        await durable_operations().get(observed_workflow_id) if observed_workflow_id else None
    )
    if workflow is not None and workflow.state in {"pending", "running"}:
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


async def retry_pdf_import_batch(db: AsyncSession, user: User, batch_id: str) -> ImportBatch:
    """Retry a failed PDF Import Batch without relinquishing its staged objects."""
    batch = await db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update())
    if batch is None or batch.owner_id != user.id:
        raise ResourceUnavailable("import batch not found")
    await _converge_pdf_import_batch_status(db, batch)
    if batch.file_format != "pdf" or batch.status != "failed":
        raise BatchConflict("only a failed PDF import batch can be retried")
    pending_records = json.loads(batch.records)
    if not isinstance(pending_records, list) or not any(
        isinstance(record, dict) and isinstance(record.get("_pdf"), dict)
        for record in pending_records
    ):
        raise BatchConflict("the failed import batch has no staged PDFs to retry")

    workflow_id = f"prepare-pdf-import:{batch.id}:{uuid4()}"
    batch.status = "pending"
    batch.workflow_id = workflow_id
    await durable_operations().enqueue_in_transaction(
        db,
        "library.prepare_pdf_import",
        batch.id,
        workflow_id,
        pending_records,
        (batch.pdf_annotation_mode or PdfAnnotationMode.preserve).value,
        queue_name=IMPORT_QUEUE,
        workflow_id=workflow_id,
        attributes={
            "capability": "library",
            "operation": "prepare_pdf_import",
            "owner_id": user.id,
            "batch_id": batch.id,
            "object_keys": [record["_pdf"]["object_key"] for record in pending_records],
            "pdf_annotation_mode": (batch.pdf_annotation_mode or PdfAnnotationMode.preserve).value,
        },
    )
    record_event(db, user.id, "pdf.import.preview.retry", "import_batch", batch.id)
    await db.commit()
    return batch


async def commit_import_batch(db: AsyncSession, user: User, batch_id: str) -> None:
    batch = await db.get(ImportBatch, batch_id)
    if batch is None or batch.owner_id != user.id:
        raise ResourceUnavailable("import batch not found")
    if batch.status != "ready":
        raise BatchConflict("the import batch is still being prepared")
    errors = json.loads(batch.errors)
    if errors and batch.file_format != "pdf":
        raise BatchConflict("the preview contains errors")
    records = json.loads(batch.records)
    if not records:
        raise BatchConflict("the import batch has no candidate records")
    if batch.file_format == "pdf":
        known_dois = {
            value
            for provider, value in await get_accessible_item_identifiers(db, user)
            if provider == "doi"
        }
        candidate_dois: set[str] = set()
        for record in records:
            doi = record.get("doi") if isinstance(record, dict) else None
            normalized_doi = doi.strip().casefold() if isinstance(doi, str) else ""
            if normalized_doi in known_dois:
                raise BatchConflict("an accessible Item already has this DOI")
            if normalized_doi and normalized_doi in candidate_dois:
                raise BatchConflict("another PDF in this batch has the same DOI")
            if normalized_doi:
                candidate_dois.add(normalized_doi)
    for record in records:
        candidate = dict(record)
        pdf = candidate.pop("_pdf", None)
        item = await _create_item_from_record(db, user, candidate)
        if pdf is not None:
            await attach_staged_pdf(
                db,
                user,
                item,
                (
                    pdf["object_key"],
                    pdf["size"],
                    pdf["original_name"],
                ),
                annotation_mode=batch.pdf_annotation_mode or PdfAnnotationMode.preserve,
                max_pdf_bytes=batch.max_pdf_bytes or get_settings().max_pdf_bytes,
            )
        await search_index(db).index_item(db, item.id)
        record_event(
            db,
            user.id,
            "pdf.import" if pdf is not None else "bibliography.import",
            "item",
            item.id,
            detail={
                "format": batch.file_format,
                "filename": pdf["original_name"] if pdf else None,
                "annotation_mode": (
                    (batch.pdf_annotation_mode or PdfAnnotationMode.preserve).value
                    if pdf is not None
                    else None
                ),
            },
        )
    await db.delete(batch)
    await db.commit()


async def discard_import_batch(db: AsyncSession, user: User, batch_id: str) -> None:
    batch = await db.get(ImportBatch, batch_id)
    if batch is None or batch.owner_id != user.id:
        raise ResourceUnavailable("import batch not found")
    object_keys = _pdf_object_keys(batch.records)
    record_event(db, user.id, "import.batch.discard", "import_batch", batch.id)
    await db.delete(batch)
    await enqueue_object_cleanup(
        db,
        object_keys,
        owner_id=user.id,
        operation="import_batch_discard",
        target_id=batch.id,
    )
    await db.commit()


async def export_accessible_bibliography(
    db: AsyncSession,
    user: User,
    file_format: str,
    style_key: str = "apa",
    options: BibliographyExportOptions | None = None,
) -> tuple[str, str, str]:
    items = list(
        (
            await db.scalars(
                visible_items_query(user)
                .options(selectinload(Item.author_links).selectinload(ItemAuthor.author))
                .order_by(Item.updated_at.desc())
            )
        ).all()
    )
    if file_format == "csl":
        return await format_csl_export(db, user, items, style_key=style_key, options=options)
    return format_standard_export(items, file_format, options=options)


async def export_selected_bibliography(
    db: AsyncSession,
    user: User,
    item_ids: list[str],
    file_format: str,
    style_key: str = "apa",
    options: BibliographyExportOptions | None = None,
) -> tuple[str, str, str]:
    items = await require_accessible_items(db, user, item_ids)
    if file_format == "csl":
        return await format_csl_export(db, user, items, style_key=style_key, options=options)
    return format_standard_export(items, file_format, options=options)
