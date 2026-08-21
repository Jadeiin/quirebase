from __future__ import annotations

import json
from typing import TYPE_CHECKING, BinaryIO

from quirebase.access.items import require_accessible_items, visible_items_query
from quirebase.audit import record_event
from quirebase.core.config import Settings, get_settings
from quirebase.core.errors import (
    DomainError,
    ResourceNotFound,
    ResourceUnavailable,
    SizeLimitExceeded,
    ValidationFailure,
)
from quirebase.core.storage import LocalObjectStore
from quirebase.discovery.activity import get_accessible_item_identifiers
from quirebase.discovery.bibliography import (
    SUPPORTED_FORMATS,
    parse_bibliography,
)
from quirebase.discovery.citations import (
    ExportOptions,
    format_csl_export,
    format_standard_export,
)
from quirebase.discovery.lookup import (
    MetadataLookupError,
    MetadataNotFoundError,
    MetadataRecord,
    lookup_metadata,
)
from quirebase.documents import delete_unreferenced_objects
from quirebase.documents.revisions import attach_staged_pdf, stage_pdf
from quirebase.models import ImportBatch, Item, User
from quirebase.pipeline.inspection import extract_doi
from quirebase.search import search_index

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx
    from sqlalchemy.orm import Session


class BatchConflict(DomainError):
    pass


class UpstreamServiceError(DomainError):
    pass


MAX_PDF_IMPORT_FILES = 50


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


def stage_import_batch(
    db: Session, user: User, file_bytes: bytes, file_format: str
) -> tuple[ImportBatch, list[dict], list[dict]]:
    if file_format not in SUPPORTED_FORMATS:
        raise ValidationFailure("format must be bibtex, ris, or endnote")
    if len(file_bytes) > 5 * 1024 * 1024:
        raise SizeLimitExceeded("bibliography files are limited to 5 MiB")
    try:
        contents = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValidationFailure("bibliography must be UTF-8") from error
    records, errors = parse_bibliography(contents, file_format)
    batch = ImportBatch(
        owner_id=user.id,
        file_format=file_format,
        records=json.dumps(records, ensure_ascii=False),
        errors=json.dumps(errors, ensure_ascii=False),
    )
    db.add(batch)
    db.commit()
    return batch, records, errors


def stage_identifier_import_batch(
    db: Session,
    user: User,
    identifier: str,
    provider: str = "auto",
    transport: httpx.BaseTransport | None = None,
    settings: Settings | None = None,
) -> tuple[ImportBatch, list[dict], list[dict]]:
    from quirebase.operations.settings import get_effective_settings_model

    effective_settings = settings or get_effective_settings_model(db)
    try:
        parsed, record = lookup_metadata(
            identifier,
            provider,
            settings=effective_settings,
            transport=transport,
        )
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    except MetadataNotFoundError as error:
        raise ResourceNotFound(str(error)) from error
    except MetadataLookupError as error:
        raise UpstreamServiceError(str(error)) from error
    rec_dict = record.to_dict() if isinstance(record, MetadataRecord) else record
    batch = ImportBatch(
        owner_id=user.id,
        file_format=f"metadata:{parsed.provider}",
        records=json.dumps([rec_dict], ensure_ascii=False),
        errors="[]",
    )
    db.add(batch)
    db.flush()
    record_event(
        db,
        user.id,
        "metadata.lookup",
        "import_batch",
        batch.id,
        detail={"provider": parsed.provider},
    )
    db.commit()
    return batch, [rec_dict], []


def stage_pdf_import_batch(
    db: Session,
    user: User,
    uploads: Sequence[tuple[BinaryIO, str]],
    *,
    max_bytes: int | None = None,
    settings: Settings | None = None,
) -> tuple[ImportBatch, list[dict], list[dict]]:
    from quirebase.operations.settings import get_effective_setting, get_effective_settings_model

    if not uploads:
        raise ValidationFailure("at least one PDF is required")
    if len(uploads) > MAX_PDF_IMPORT_FILES:
        raise ValidationFailure(f"a PDF import batch is limited to {MAX_PDF_IMPORT_FILES} files")

    effective_settings = settings or get_effective_settings_model(db)
    if max_bytes is None:
        max_bytes = get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes)
    known_dois = {
        value for provider, value in get_accessible_item_identifiers(db, user) if provider == "doi"
    }
    batch_dois: set[str] = set()
    retained_keys: set[str] = set()
    records: list[dict] = []
    errors: list[dict] = []

    try:
        for row, (source, filename) in enumerate(uploads, start=1):
            staged: tuple[str, str, int, str] | None = None
            diagnostic_code = "invalid_pdf"
            try:
                staged = stage_pdf(source, filename, max_bytes)
                detected_doi = extract_doi(LocalObjectStore().path(staged[0]))
                if not detected_doi:
                    diagnostic_code = "missing_doi"
                    raise ValidationFailure("no DOI was found in this PDF")
                normalized_doi = detected_doi.casefold()
                if normalized_doi in known_dois:
                    diagnostic_code = "existing_doi"
                    raise BatchConflict("an accessible Item already has this DOI")
                if normalized_doi in batch_dois:
                    diagnostic_code = "duplicate_batch_doi"
                    raise BatchConflict("another PDF in this batch has the same DOI")
                try:
                    _identifier, record = lookup_metadata(
                        detected_doi,
                        "doi",
                        settings=effective_settings,
                    )
                except ValueError as error:
                    diagnostic_code = "invalid_doi"
                    raise ValidationFailure(str(error)) from error
                except MetadataNotFoundError as error:
                    diagnostic_code = "metadata_not_found"
                    raise ResourceNotFound(str(error)) from error
                except MetadataLookupError as error:
                    diagnostic_code = "metadata_lookup_failed"
                    raise UpstreamServiceError(str(error)) from error

                rec_dict = record.to_dict() if isinstance(record, MetadataRecord) else dict(record)
                rec_dict.setdefault("doi", detected_doi)
                rec_dict["_pdf"] = {
                    "object_key": staged[0],
                    "sha256": staged[1],
                    "size": staged[2],
                    "original_name": staged[3],
                    "detected_doi": detected_doi,
                }
                records.append(rec_dict)
                batch_dois.add(normalized_doi)
                retained_keys.add(staged[0])
            except DomainError as error:
                errors.append({
                    "row": row,
                    "filename": filename,
                    "code": diagnostic_code,
                    "message": str(error),
                })
                if staged is not None and staged[0] not in retained_keys:
                    delete_unreferenced_objects(db, (staged[0],))

        batch = ImportBatch(
            owner_id=user.id,
            file_format="pdf",
            records=json.dumps(records, ensure_ascii=False),
            errors=json.dumps(errors, ensure_ascii=False),
        )
        db.add(batch)
        db.flush()
        record_event(
            db,
            user.id,
            "pdf.import.preview",
            "import_batch",
            batch.id,
            detail={"candidates": len(records), "diagnostics": len(errors)},
        )
        db.commit()
        return batch, records, errors
    except Exception:
        db.rollback()
        delete_unreferenced_objects(db, retained_keys)
        raise


def _create_item_from_record(db: Session, user: User, record: dict | MetadataRecord) -> Item:
    # Imported lazily: library.identifiers imports this package, so a
    # module-level import would deadlock during package initialization.
    from quirebase.library import create_item_from_metadata_record

    return create_item_from_metadata_record(db, user, record)


def commit_import_batch(db: Session, user: User, batch_id: str) -> None:
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.owner_id != user.id:
        raise ResourceUnavailable("import batch not found")
    errors = json.loads(batch.errors)
    if errors and batch.file_format != "pdf":
        raise BatchConflict("the preview contains errors")
    records = json.loads(batch.records)
    if not records:
        raise BatchConflict("the import batch has no candidate records")
    if batch.file_format == "pdf":
        known_dois = {
            value
            for provider, value in get_accessible_item_identifiers(db, user)
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
        item = _create_item_from_record(db, user, candidate)
        if pdf is not None:
            attach_staged_pdf(
                db,
                user,
                item,
                (
                    pdf["object_key"],
                    pdf["sha256"],
                    pdf["size"],
                    pdf["original_name"],
                ),
            )
        search_index(db).index_item(db, item.id)
        record_event(
            db,
            user.id,
            "pdf.import" if pdf is not None else "bibliography.import",
            "item",
            item.id,
            detail={"format": batch.file_format, "filename": pdf["original_name"] if pdf else None},
        )
    db.delete(batch)
    db.commit()


def discard_import_batch(db: Session, user: User, batch_id: str) -> None:
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.owner_id != user.id:
        raise ResourceUnavailable("import batch not found")
    object_keys = _pdf_object_keys(batch.records)
    record_event(db, user.id, "import.batch.discard", "import_batch", batch.id)
    db.delete(batch)
    db.commit()
    delete_unreferenced_objects(db, object_keys)


def export_accessible_bibliography(
    db: Session,
    user: User,
    file_format: str,
    style_key: str = "apa",
    options: ExportOptions | None = None,
) -> tuple[str, str, str]:
    items = list(db.scalars(visible_items_query(user).order_by(Item.updated_at.desc())).all())
    if file_format == "csl":
        return format_csl_export(db, user, items, style_key=style_key, options=options)
    return format_standard_export(items, file_format, options=options)


def export_selected_bibliography(
    db: Session,
    user: User,
    item_ids: list[str],
    file_format: str,
    style_key: str = "apa",
    options: ExportOptions | None = None,
) -> tuple[str, str, str]:
    items = require_accessible_items(db, user, item_ids)
    if file_format == "csl":
        return format_csl_export(db, user, items, style_key=style_key, options=options)
    return format_standard_export(items, file_format, options=options)
