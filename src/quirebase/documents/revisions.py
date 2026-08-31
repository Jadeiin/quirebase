from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from quirebase.access.documents import require_attachment, require_revision
from quirebase.access.items import can_edit_item, require_editable_item, require_readable_item
from quirebase.audit import record_event
from quirebase.core.config import get_settings
from quirebase.core.errors import (
    DomainError,
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
    VersionConflict,
)
from quirebase.core.storage import LocalObjectStore, ObjectLease
from quirebase.models import (
    Attachment,
    AttachmentRole,
    FileRevision,
    ImportBatch,
    Item,
    Job,
    JobState,
    Project,
    ProjectItem,
    ProjectMember,
    User,
)
from quirebase.pipeline.derived_state import propagate_file_revision_change
from quirebase.pipeline.inspection import job_payload, validate_pdf_container

if TYPE_CHECKING:
    from collections.abc import Iterable


class UnsupportedMediaType(DomainError):
    pass


GRAPHICAL_ABSTRACT_MEDIA_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}


@dataclass
class StagedPdf:
    object_key: str
    sha256: str
    size: int
    original_name: str
    _lease: ObjectLease = field(repr=False)

    def revision_data(self) -> tuple[str, str, int, str]:
        return self.object_key, self.sha256, self.size, self.original_name

    def release(self) -> None:
        self._lease.release()


@dataclass(frozen=True)
class ItemThumbnail:
    path: Path
    media_type: str
    source_kind: str
    source_id: str


def stage_pdf(source: BinaryIO, filename: str, max_bytes: int) -> StagedPdf:
    if not filename or not filename.lower().endswith(".pdf"):
        raise UnsupportedMediaType("a PDF file is required")
    store = LocalObjectStore()
    try:
        key, digest, size, lease = store.put_staged_pdf(source, max_bytes)
        validate_pdf_container(store.path(key))
    except ValueError as error:
        if "lease" in locals():
            lease.release()
        if "key" in locals():
            with store.cleanup_lock(key):
                if not store.has_active_lease(key):
                    store.delete(key)
        raise ValidationFailure(str(error)) from error
    return StagedPdf(key, digest, size, Path(filename).name, lease)


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
    record_event(db, user.id, "pdf.upload", "file_revision", revision.id)
    return revision


def _pdf_import_object_keys(records_json: str) -> set[str]:
    try:
        records = json.loads(records_json)
    except (json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(records, list):
        return set()
    return {
        object_key
        for record in records
        if isinstance(record, dict)
        and isinstance((pdf := record.get("_pdf")), dict)
        and isinstance((object_key := pdf.get("object_key")), str)
    }


def _object_is_referenced(db: Session, object_key: str) -> bool:
    if db.scalar(select(FileRevision.object_key).where(FileRevision.object_key == object_key)):
        return True
    if db.scalar(select(Attachment.object_key).where(Attachment.object_key == object_key)):
        return True
    return any(
        object_key in _pdf_import_object_keys(records)
        for records in db.scalars(
            select(ImportBatch.records).where(ImportBatch.file_format == "pdf")
        )
    )


def delete_unreferenced_objects(db: Session, object_keys: Iterable[str]) -> tuple[str, ...]:
    """Delete objects only when no committed, pending, or in-flight record references them."""
    keys = tuple(dict.fromkeys(key for key in object_keys if key))
    if not keys:
        return ()
    store = LocalObjectStore()
    actually_deleted: list[str] = []
    for object_key in keys:
        with store.cleanup_lock(object_key):
            if store.has_active_lease(object_key):
                continue
            with Session(db.bind) as check_db:
                if _object_is_referenced(check_db, object_key):
                    continue
            store.delete(object_key)
            actually_deleted.append(object_key)
    return tuple(actually_deleted)


def discard_staged_object(db: Session, object_key: str) -> None:
    delete_unreferenced_objects(db, (object_key,))


def store_pdf_revision(
    db: Session,
    user: User,
    item_id: str,
    source: BinaryIO,
    filename: str,
    max_bytes: int | None = None,
) -> FileRevision:
    from quirebase.operations.settings import get_effective_setting

    item = require_editable_item(db, user, item_id)
    if max_bytes is None:
        max_bytes = get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes)
    staged = stage_pdf(source, filename, max_bytes)
    try:
        revision = attach_staged_pdf(db, user, item, staged.revision_data())
        db.commit()
    except Exception:
        db.rollback()
        staged.release()
        discard_staged_object(db, staged.object_key)
        raise
    staged.release()
    return revision


def _is_image_container(path: Path, content_type: str) -> bool:
    with path.open("rb") as source:
        header = source.read(12)
    return {
        "image/gif": header.startswith((b"GIF87a", b"GIF89a")),
        "image/jpeg": header.startswith(b"\xff\xd8\xff"),
        "image/png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
    }.get(content_type, False)


def _lock_item_for_attachment_role_replacement(db: Session, item_id: str) -> None:
    if db.get_bind().dialect.name == "sqlite":
        locked_item_id = db.scalar(
            update(Item)
            .where(Item.id == item_id)
            .values(updated_at=Item.updated_at)
            .returning(Item.id)
        )
    else:
        locked_item_id = db.scalar(select(Item.id).where(Item.id == item_id).with_for_update())
    if locked_item_id is None:
        raise ResourceUnavailable("item not accessible")


def create_attachment(
    db: Session,
    user: User,
    item_id: str,
    source: BinaryIO,
    filename: str,
    content_type: str = "application/octet-stream",
    max_bytes: int | None = None,
    role: AttachmentRole | None = None,
) -> Attachment:
    from quirebase.operations.settings import get_effective_setting

    if not can_edit_item(db, user, item_id) or not filename:
        raise ResourceUnavailable("item not accessible or filename missing")
    if max_bytes is None:
        max_bytes = get_effective_setting(
            db, "max_attachment_bytes", get_settings().max_attachment_bytes
        )
    if role == AttachmentRole.graphical_abstract and content_type not in (
        GRAPHICAL_ABSTRACT_MEDIA_TYPES
    ):
        raise ValidationFailure("graphical abstract must be a PNG, JPEG, WebP, or GIF image")
    store = LocalObjectStore()
    try:
        key, digest, size, lease = store.put_staged_attachment(source, max_bytes)
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    if role == AttachmentRole.graphical_abstract and not _is_image_container(
        store.path(key), content_type
    ):
        lease.release()
        discard_staged_object(db, key)
        raise ValidationFailure("graphical abstract content does not match its image type")
    try:
        if role is not None:
            _lock_item_for_attachment_role_replacement(db, item_id)
            current = db.scalar(
                select(Attachment).where(
                    Attachment.item_id == item_id,
                    Attachment.role == role,
                )
            )
            if current is not None:
                current.role = None
                db.flush()
        record = Attachment(
            item_id=item_id,
            object_key=key,
            sha256=digest,
            size=size,
            mime_type=content_type[:100],
            original_name=Path(filename).name[:255],
            role=role,
            created_by=user.id,
        )
        db.add(record)
        db.flush()
        record_event(db, user.id, "attachment.upload", "attachment", record.id)
        db.commit()
    except Exception:
        db.rollback()
        lease.release()
        discard_staged_object(db, key)
        raise
    lease.release()
    return record


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


def get_revision_thumbnail(
    db: Session, user: User, item_id: str, revision_id: str
) -> Path:
    revision = require_revision(db, user, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    path = get_settings().object_dir / "thumbnails" / f"{revision.id}.png"
    if not path.is_file():
        raise ResourceNotFound("revision thumbnail not found")
    return path


def get_item_thumbnail(db: Session, user: User, item_id: str) -> ItemThumbnail:
    require_readable_item(db, user, item_id)
    graphical_abstract = db.scalar(
        select(Attachment).where(
            Attachment.item_id == item_id,
            Attachment.role == AttachmentRole.graphical_abstract,
        )
    )
    if graphical_abstract is not None:
        path = LocalObjectStore().path(graphical_abstract.object_key)
        if path.is_file():
            return ItemThumbnail(
                path=path,
                media_type=graphical_abstract.mime_type,
                source_kind="graphical_abstract",
                source_id=graphical_abstract.id,
            )
    revisions = db.scalars(
        select(FileRevision)
        .where(
            FileRevision.item_id == item_id,
            FileRevision.processing_state == "ready",
        )
        .order_by(FileRevision.created_at.desc())
    ).all()
    for revision in revisions:
        path = get_settings().object_dir / "thumbnails" / f"{revision.id}.png"
        if path.is_file():
            return ItemThumbnail(
                path=path,
                media_type="image/png",
                source_kind="pdf_thumbnail",
                source_id=revision.id,
            )
    raise ResourceNotFound("item thumbnail not found")


def _job_targets_revision(job: Job, revision_id: str) -> bool:
    try:
        payload = json.loads(job.payload)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(payload, dict) and payload.get("revision_id") == revision_id


def delete_file_revision(
    db: Session, user: User, item_id: str, revision_id: str
) -> None:
    require_editable_item(db, user, item_id)
    revision = db.scalar(
        select(FileRevision).where(FileRevision.id == revision_id).with_for_update()
    )
    if revision is None or revision.item_id != item_id:
        raise ResourceNotFound("file revision not found")
    inspection_job = db.scalar(
        select(Job)
        .where(
            Job.kind == "pdf.inspect",
            Job.idempotency_key == f"pdf.inspect:{revision_id}",
        )
        .with_for_update()
    )
    export_jobs = tuple(
        job
        for job in db.scalars(
            select(Job)
            .where(
                Job.kind == "pdf.export_annotations",
                Job.state.in_([JobState.pending, JobState.running, JobState.failed]),
            )
            .with_for_update()
        ).all()
        if _job_targets_revision(job, revision_id)
    )
    revision_jobs = tuple(job for job in (inspection_job, *export_jobs) if job is not None)
    if any(job.state == JobState.running for job in revision_jobs):
        raise VersionConflict(message="PDF background work is still running; retry deletion shortly")
    object_key = revision.object_key
    thumbnail = get_settings().object_dir / "thumbnails" / f"{revision.id}.png"
    for job in revision_jobs:
        if job.state in {JobState.pending, JobState.failed}:
            db.delete(job)
    db.delete(revision)
    db.flush()
    propagate_file_revision_change(db, item_id, owner_id=user.id)
    record_event(db, user.id, "pdf.delete", "file_revision", revision.id)
    db.commit()
    with contextlib.suppress(OSError):
        thumbnail.unlink(missing_ok=True)
    delete_unreferenced_objects(db, (object_key,))


def delete_attachment(db: Session, user: User, item_id: str, attachment_id: str) -> None:
    require_editable_item(db, user, item_id)
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.item_id != item_id:
        raise ResourceNotFound("attachment not found")
    object_key = attachment.object_key
    db.delete(attachment)
    record_event(db, user.id, "attachment.delete", "attachment", attachment.id)
    db.commit()
    delete_unreferenced_objects(db, (object_key,))


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
