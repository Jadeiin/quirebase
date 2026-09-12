from __future__ import annotations

import asyncio
import hashlib
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

from quirebase.access.items import (
    lock_user_write_gate,
    require_accessible_items,
    visible_items_query,
)
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
from quirebase.library.identifiers import normalize_operation_id
from quirebase.library.providers import candidate_record_values, lookup_candidate
from quirebase.models import ImportBatch, Item, ItemAuthor, User
from quirebase.search import enqueue_search_changed

if TYPE_CHECKING:
    from collections.abc import Sequence

    from inquiro.bibliography import BibliographyExportOptions
    from sqlalchemy.ext.asyncio import AsyncSession


class BatchConflict(DomainError):
    pass


MAX_PDF_IMPORT_FILES = 50


def _derive_import_item_operation_id(batch_id: str, commit_operation_id: str, index: int) -> str:
    """Return a stable, storage-bounded idempotency key for one imported Item."""

    digest = hashlib.sha256(f"{batch_id}\0{commit_operation_id}\0{index}".encode()).hexdigest()
    operation_id = normalize_operation_id(f"import-item:{digest}")
    assert operation_id is not None
    return operation_id


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
        created_by=user.id,
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
        created_by=user.id,
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
) -> tuple[ImportBatch, list[dict], list[dict]]:
    from quirebase.operations.settings import get_effective_setting

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
            created_by=reloaded_user.id,
            file_format="pdf",
            records=json.dumps(pending_records, ensure_ascii=False),
            errors=json.dumps(errors, ensure_ascii=False),
            status="pending",
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
            queue_name=IMPORT_QUEUE,
            workflow_id=workflow_id,
            attributes={
                "capability": "library",
                "operation": "prepare_pdf_import",
                "owner_id": reloaded_user.id,
                "batch_id": batch.id,
                "object_keys": [staged.object_key for staged in staged_pdfs],
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
    user = await db.get(User, batch.created_by)
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
    user = await db.get(User, batch.created_by)
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
    owner = await db.get(User, batch.created_by)
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
        batch.created_by,
        "pdf.import.preview",
        "import_batch",
        batch.id,
        detail={"candidates": len(records), "diagnostics": len(initial_errors) + len(errors)},
    )
    return True


async def _create_item_from_record(
    db: AsyncSession, user: User, record: dict, *, operation_id: str | None = None
) -> Item:
    from quirebase.library import create_item_from_metadata_record

    return await create_item_from_metadata_record(db, user, record, operation_id=operation_id)


async def get_import_batch_preview(
    db: AsyncSession, user: User, batch_id: str
) -> tuple[ImportBatch, list[dict], list[dict]]:
    batch = await db.get(ImportBatch, batch_id)
    if batch is None or batch.created_by != user.id:
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
    if batch is None or batch.created_by != user.id:
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
        queue_name=IMPORT_QUEUE,
        workflow_id=workflow_id,
        attributes={
            "capability": "library",
            "operation": "prepare_pdf_import",
            "owner_id": user.id,
            "batch_id": batch.id,
            "object_keys": [record["_pdf"]["object_key"] for record in pending_records],
        },
    )
    record_event(db, user.id, "pdf.import.preview.retry", "import_batch", batch.id)
    await db.commit()
    return batch


async def _lock_import_batch(db: AsyncSession, batch_id: str, owner_id: str) -> ImportBatch | None:
    predicates = [ImportBatch.id == batch_id, ImportBatch.created_by == owner_id]
    return await db.scalar(select(ImportBatch).where(*predicates).with_for_update())


async def commit_import_batch(
    db: AsyncSession,
    user: User,
    batch_id: str,
    commit_operation_id: str | None = None,
) -> tuple[str, ...]:
    """Atomically confirm an Import Batch and return its stable Item IDs.

    ``ready -> committing -> committed`` is guarded by a conditional update so
    two HTTP retries cannot create duplicate Items.  The committed row is kept
    as the idempotency record; callers repeating the same operation receive the
    original result.  Staged PDF references are stripped at confirmation so the
    tombstone stops reserving object keys — only non-terminal batches may
    reserve staged objects.
    """
    await lock_user_write_gate(db, user)
    batch = await _lock_import_batch(db, batch_id, user.id)
    if batch is None:
        raise ResourceUnavailable("import batch not found")
    requested_operation = normalize_operation_id(commit_operation_id or f"import-commit:{batch.id}")
    assert requested_operation is not None
    if batch.status == "committed":
        if batch.commit_operation_id not in (None, requested_operation):
            raise BatchConflict("the import batch was committed by another operation")
        return tuple(json.loads(batch.committed_item_ids or "[]"))
    if batch.status in {"discarded", "failed", "pending"}:
        if batch.status == "failed":
            raise BatchConflict("the import batch is not ready to commit")
        raise BatchConflict("the import batch is still being prepared")
    errors = json.loads(batch.errors)
    if errors and batch.file_format != "pdf":
        raise BatchConflict("the preview contains errors")
    records = json.loads(batch.records)
    if not records:
        raise BatchConflict("the import batch has no candidate records")
    item_operation_ids = tuple(
        _derive_import_item_operation_id(batch.id, requested_operation, index)
        for index in range(len(records))
    )
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
    if batch.status == "committing":
        if batch.commit_operation_id != requested_operation:
            raise BatchConflict("the import batch is already being committed")
    else:
        result = await db.execute(
            update(ImportBatch)
            .where(ImportBatch.id == batch.id, ImportBatch.status == "ready")
            .values(status="committing", commit_operation_id=requested_operation)
        )
        if getattr(result, "rowcount", 0) != 1:
            await db.rollback()
            raise BatchConflict("the import batch is already being committed")
        await db.flush()
        await db.refresh(batch)
    committed_item_ids: list[str] = []
    for record, item_operation_id in zip(records, item_operation_ids, strict=True):
        candidate = dict(record)
        pdf = candidate.pop("_pdf", None)
        item = await _create_item_from_record(
            db,
            user,
            candidate,
            operation_id=item_operation_id,
        )
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
            )
        await enqueue_search_changed(db, item.id)
        record_event(
            db,
            user.id,
            "pdf.import" if pdf is not None else "bibliography.import",
            "item",
            item.id,
            detail={"format": batch.file_format, "filename": pdf["original_name"] if pdf else None},
        )
        committed_item_ids.append(item.id)
    batch.status = "committed"
    batch.commit_operation_id = requested_operation
    batch.committed_item_ids = json.dumps(committed_item_ids)
    # The tombstone keeps the bibliographic payload for audit but drops every
    # staged ``_pdf`` entry: a committed batch must not keep reserving object
    # keys after the Items own the files.
    batch.records = json.dumps(
        [{key: value for key, value in record.items() if key != "_pdf"} for record in records],
        ensure_ascii=False,
    )
    record_event(
        db,
        user.id,
        "import.batch.commit",
        "import_batch",
        batch.id,
        detail={"items": len(committed_item_ids), "operation_id": requested_operation},
    )
    await db.commit()
    return tuple(committed_item_ids)


async def discard_import_batch(db: AsyncSession, user: User, batch_id: str) -> None:
    batch = await _lock_import_batch(db, batch_id, user.id)
    if batch is None:
        raise ResourceUnavailable("import batch not found")
    # The locked read plus the discardable-status check serialize this terminal
    # transition against confirmation. The discarded tombstone is retained so
    # a retry can be answered idempotently without recreating staged objects.
    if batch.status == "discarded":
        await db.commit()
        return
    if batch.status in {"committing", "committed"}:
        raise BatchConflict("the import batch is being committed or was already committed")
    object_keys = _pdf_object_keys(batch.records)
    record_event(db, user.id, "import.batch.discard", "import_batch", batch.id)
    batch.status = "discarded"
    try:
        records = json.loads(batch.records)
    except (json.JSONDecodeError, TypeError):
        records = []
    if isinstance(records, list):
        batch.records = json.dumps(
            [
                {key: value for key, value in record.items() if key != "_pdf"}
                for record in records
                if isinstance(record, dict)
            ],
            ensure_ascii=False,
        )
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
