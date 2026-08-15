from __future__ import annotations

import json
from typing import TYPE_CHECKING, BinaryIO

from quirebase.access.items import can_read_item, visible_items_query
from quirebase.core.config import Settings, get_settings
from quirebase.core.errors import (
    DomainError,
    ResourceNotFound,
    ResourceUnavailable,
    SizeLimitExceeded,
    ValidationFailure,
)
from quirebase.core.storage import LocalObjectStore
from quirebase.discovery.bibliography import (
    SUPPORTED_FORMATS,
    parse_bibliography,
)
from quirebase.discovery.citations import (
    format_csl_export,
    format_standard_export,
)
from quirebase.discovery.lookup import (
    MetadataLookupError,
    MetadataNotFoundError,
    lookup_metadata,
)
from quirebase.documents.revisions import (
    attach_staged_pdf,
    discard_staged_object,
    stage_pdf,
)
from quirebase.library.audit import record_audit_event
from quirebase.models import ImportBatch, Item, User
from quirebase.pipeline.inspection import extract_doi
from quirebase.search import search_index

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.orm import Session


class BatchConflict(DomainError):
    pass


class UpstreamServiceError(DomainError):
    pass


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


def stage_metadata_batch(
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
        if transport is not None:
            try:
                parsed, record = lookup_metadata(
                    identifier, provider, settings=effective_settings, transport=transport
                )
            except TypeError:
                parsed, record = lookup_metadata(identifier, provider, transport=transport)
        else:
            try:
                parsed, record = lookup_metadata(identifier, provider, settings=effective_settings)
            except TypeError:
                parsed, record = lookup_metadata(identifier, provider)
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    except MetadataNotFoundError as error:
        raise ResourceNotFound(str(error)) from error
    except MetadataLookupError as error:
        raise UpstreamServiceError(str(error)) from error
    batch = ImportBatch(
        owner_id=user.id,
        file_format=f"metadata:{parsed.provider}",
        records=json.dumps([record], ensure_ascii=False),
        errors="[]",
    )
    db.add(batch)
    db.flush()
    record_audit_event(
        db,
        user.id,
        "metadata.lookup",
        "import_batch",
        batch.id,
        detail={"provider": parsed.provider},
    )
    db.commit()
    return batch, [record], []


def commit_import_batch(db: Session, user: User, batch_id: str) -> None:
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.owner_id != user.id:
        raise ResourceUnavailable("import batch not found")
    errors = json.loads(batch.errors)
    if errors:
        raise BatchConflict("the preview contains errors")
    records = json.loads(batch.records)
    for record in records:
        item = Item(created_by=user.id, **record)
        db.add(item)
        db.flush()
        search_index(db).index_item(db, item.id)
        record_audit_event(
            db,
            user.id,
            "bibliography.import",
            "item",
            item.id,
            detail={"format": batch.file_format},
        )
    db.delete(batch)
    db.commit()


def import_published_pdf(
    db: Session,
    user: User,
    source: BinaryIO,
    filename: str,
    doi: str = "",
    max_bytes: int | None = None,
) -> Item:
    from quirebase.operations.settings import get_effective_setting, get_effective_settings_model

    if max_bytes is None:
        max_bytes = get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes)
    staged = stage_pdf(source, filename, max_bytes)
    try:
        detected_doi = extract_doi(LocalObjectStore().path(staged[0]))
        identifier = doi.strip() or detected_doi
        if not identifier:
            raise ValidationFailure(
                "no DOI was found in the PDF; enter one manually or import it as unpublished"
            )
        try:
            try:
                _identifier, record = lookup_metadata(
                    identifier, "doi", settings=get_effective_settings_model(db)
                )
            except TypeError:
                _identifier, record = lookup_metadata(identifier, "doi")
        except ValueError as error:
            raise ValidationFailure(str(error)) from error
        except MetadataNotFoundError as error:
            raise ResourceNotFound(str(error)) from error
        except MetadataLookupError as error:
            raise UpstreamServiceError(str(error)) from error

        item = Item(created_by=user.id, **record)
        db.add(item)
        db.flush()
        attach_staged_pdf(db, user, item, staged)
        search_index(db).index_item(db, item.id)
        record_audit_event(
            db,
            user.id,
            "import.pdf.published",
            "item",
            item.id,
            detail={
                "doi": item.doi,
                "detected_automatically": not bool(doi.strip()),
            },
        )
        db.commit()
        return item
    except Exception:
        db.rollback()
        discard_staged_object(db, staged[0])
        raise


def import_unpublished_pdf(
    db: Session,
    user: User,
    source: BinaryIO,
    filename: str,
    title: str,
    authors: str = "",
    abstract: str = "",
    keywords: str = "",
    max_bytes: int | None = None,
) -> Item:
    from quirebase.operations.settings import get_effective_setting

    if not title.strip():
        raise ValidationFailure("title is required")
    if max_bytes is None:
        max_bytes = get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes)
    staged = stage_pdf(source, filename, max_bytes)
    try:
        item = Item(
            title=title.strip(),
            authors=authors.strip() or None,
            abstract=abstract.strip() or None,
            keywords=keywords.strip() or None,
            reference_type="unpublished",
            created_by=user.id,
        )
        db.add(item)
        db.flush()
        attach_staged_pdf(db, user, item, staged)
        search_index(db).index_item(db, item.id)
        record_audit_event(db, user.id, "import.pdf.unpublished", "item", item.id)
        db.commit()
        return item
    except Exception:
        db.rollback()
        discard_staged_object(db, staged[0])
        raise


def export_accessible_bibliography(
    db: Session, user: User, file_format: str, style_key: str = "apa"
) -> tuple[str, str, str]:
    items = list(db.scalars(visible_items_query(user).order_by(Item.updated_at.desc())).all())
    if file_format == "csl":
        return format_csl_export(db, user, items, style_key=style_key)
    return format_standard_export(items, file_format)


def export_selected_bibliography(
    db: Session,
    user: User,
    item_ids: list[str],
    file_format: str,
    style_key: str = "apa",
) -> tuple[str, str, str]:
    unique_ids = list(dict.fromkeys(item_ids))
    selected = [db.get(Item, item_id) for item_id in unique_ids]
    items = [item for item in selected if item is not None and can_read_item(db, user, item.id)]
    if not items or len(items) != len(selected):
        raise ValidationFailure("select one or more accessible papers")
    if file_format == "csl":
        return format_csl_export(db, user, items, style_key=style_key)
    return format_standard_export(items, file_format)
