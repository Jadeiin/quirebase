from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from quirebase.access.documents import require_attachment, require_revision
from quirebase.access.items import can_edit_item, require_editable_item
from quirebase.core.config import get_settings
from quirebase.core.errors import (
    DomainError,
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.core.storage import LocalObjectStore
from quirebase.library.audit import record_audit_event
from quirebase.models import (
    Attachment,
    FileRevision,
    Item,
    Job,
    Project,
    ProjectItem,
    ProjectMember,
    User,
)
from quirebase.pipeline.inspection import job_payload, validate_pdf_container


class UnsupportedMediaType(DomainError):
    pass


def stage_pdf(source: BinaryIO, filename: str, max_bytes: int) -> tuple[str, str, int, str]:
    if not filename or not filename.lower().endswith(".pdf"):
        raise UnsupportedMediaType("a PDF file is required")
    store = LocalObjectStore()
    try:
        key, digest, size = store.put_pdf(source, max_bytes)
        validate_pdf_container(store.path(key))
    except ValueError as error:
        if "key" in locals():
            store.path(key).unlink(missing_ok=True)
        raise ValidationFailure(str(error)) from error
    return key, digest, size, Path(filename).name


def attach_staged_pdf(
    db: Session,
    user: User,
    item: Item,
    staged: tuple[str, str, int, str],
) -> FileRevision:
    key, digest, size, original_name = staged
    revision = FileRevision(
        item_id=item.id,
        object_key=key,
        sha256=digest,
        size=size,
        original_name=original_name,
        created_by=user.id,
    )
    db.add(revision)
    db.flush()
    db.add(
        Job(
            kind="pdf.inspect",
            payload=job_payload(revision_id=revision.id),
            idempotency_key=f"pdf.inspect:{revision.id}",
            owner_id=user.id,
        )
    )
    record_audit_event(db, user.id, "pdf.upload", "file_revision", revision.id)
    return revision


def discard_staged_object(db: Session, object_key: str) -> None:
    """Remove a staged object only when no committed record references it."""
    with Session(db.bind) as check_db:
        used = check_db.scalar(
            select(FileRevision.id).where(FileRevision.object_key == object_key).limit(1)
        ) or check_db.scalar(
            select(Attachment.id).where(Attachment.object_key == object_key).limit(1)
        )
    if not used:
        LocalObjectStore().delete(object_key)


def store_pdf_revision(
    db: Session,
    user: User,
    item_id: str,
    source: BinaryIO,
    filename: str,
    max_bytes: int | None = None,
) -> FileRevision:
    item = require_editable_item(db, user, item_id)
    if max_bytes is None:
        max_bytes = get_settings().max_pdf_bytes
    staged = stage_pdf(source, filename, max_bytes)
    try:
        revision = attach_staged_pdf(db, user, item, staged)
        db.commit()
        return revision
    except Exception:
        db.rollback()
        discard_staged_object(db, staged[0])
        raise


def create_attachment(
    db: Session,
    user: User,
    item_id: str,
    source: BinaryIO,
    filename: str,
    content_type: str = "application/octet-stream",
    max_bytes: int | None = None,
) -> Attachment:
    if not can_edit_item(db, user, item_id) or not filename:
        raise ResourceUnavailable("item not accessible or filename missing")
    if max_bytes is None:
        max_bytes = get_settings().max_attachment_bytes
    try:
        key, digest, size = LocalObjectStore().put_attachment(source, max_bytes)
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    try:
        record = Attachment(
            item_id=item_id,
            object_key=key,
            sha256=digest,
            size=size,
            mime_type=content_type[:100],
            original_name=Path(filename).name[:255],
            created_by=user.id,
        )
        db.add(record)
        db.flush()
        record_audit_event(db, user.id, "attachment.upload", "attachment", record.id)
        db.commit()
        return record
    except Exception:
        db.rollback()
        discard_staged_object(db, key)
        raise


def get_attachment_file(
    db: Session, user: User, item_id: str, attachment_id: str
) -> tuple[Path, str, str]:
    record = require_attachment(db, user, item_id, attachment_id)
    return (
        LocalObjectStore().path(record.object_key),
        record.original_name,
        record.mime_type or "application/octet-stream",
    )


def get_revision_file(
    db: Session, user: User, item_id: str, revision_id: str
) -> tuple[Path, str, str]:
    revision = require_revision(db, user, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    return (
        LocalObjectStore().path(revision.object_key),
        revision.original_name,
        revision.sha256,
    )


def get_pdf_viewer_data(db: Session, user: User, item_id: str, revision_id: str) -> dict[str, Any]:
    revision = require_revision(db, user, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    projects = list(
        db.scalars(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .join(ProjectItem, ProjectItem.project_id == Project.id)
            .where(ProjectMember.user_id == user.id, ProjectItem.item_id == item_id)
            .order_by(Project.name)
        ).all()
    )
    return {
        "item": revision.item,
        "revision": revision,
        "projects": projects,
    }
