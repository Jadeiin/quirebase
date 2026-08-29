"""Document bundling and export service for single and multi-item archives."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from inquiro.richtext import convert_rich_text
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from quirebase.access.documents import require_revision
from quirebase.access.items import require_accessible_items
from quirebase.audit import record_event
from quirebase.core.errors import ResourceNotFound
from quirebase.core.storage import LocalObjectStore
from quirebase.core.timezones import annotation_export_timezone
from quirebase.documents.annotations import select_visible_annotations
from quirebase.models import Attachment, FileRevision, Item, PdfAnnotation, User
from quirebase.pipeline.inspection import export_annotations


@dataclass(frozen=True)
class ItemDownloadBundle:
    content: BytesIO
    filename: str


def _archive_name(value: str, fallback: str) -> str:
    name = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-.")
    return (name or fallback)[:80]


def _item_archive_prefix(item: Item) -> str:
    return _archive_name(
        item.bibtex_id or convert_rich_text(item.title, source="html", target="text"),
        item.id[:8],
    )


def _own_annotations(db: Session, user: User, revision_id: str) -> list[PdfAnnotation]:
    return list(
        db.scalars(
            select(PdfAnnotation)
            .options(selectinload(PdfAnnotation.segments))
            .where(
                PdfAnnotation.file_revision_id == revision_id,
                PdfAnnotation.author_id == user.id,
                PdfAnnotation.deleted_at.is_(None),
            )
            .order_by(PdfAnnotation.created_at)
        ).all()
    )


def _write_annotated_pdf(
    source: Path,
    target: Path,
    db: Session,
    user: User,
    revision_id: str,
    timezone: str | None,
) -> bool:
    """Flatten the user's annotations onto a copy; return False when none exist."""
    annotations = _own_annotations(db, user, revision_id)
    if not annotations:
        return False
    export_annotations(
        source,
        target,
        annotations,
        author_names={user.id: user.username},
        display_timezone=annotation_export_timezone(timezone),
    )
    return True


def _revision_archive_name(
    prefix: str, index: int, original_name: str, *, annotated: bool = False
) -> str:
    safe_name = _archive_name(Path(original_name).name, f"revision-{index:02d}.pdf")
    marker = "annotated-pdf" if annotated else "pdf"
    return f"{prefix}-{marker}-v{index:02d}-{safe_name}"


def _download_kind(include_annotations: bool, include_supplements: bool) -> str:
    if include_annotations and include_supplements:
        return "annotated-bundle"
    if include_annotations:
        return "annotated-pdfs"
    if include_supplements:
        return "bundle"
    return "pdfs"


def _bundle_path(root: str, filename: str) -> str:
    return f"{root}/{filename}" if root else filename


def _write_item_bundle_entries(
    bundle: zipfile.ZipFile,
    db: Session,
    user: User,
    item: Item,
    store: LocalObjectStore,
    temporary_root: Path,
    *,
    root: str = "",
    revision_ids: list[str] | None = None,
    include_annotations: bool = False,
    include_supplements: bool = False,
    timezone: str | None = None,
) -> str:
    query = (
        select(FileRevision)
        .where(FileRevision.item_id == item.id)
        .order_by(FileRevision.created_at.desc())
    )
    if revision_ids:
        query = query.where(FileRevision.id.in_(revision_ids))
    revisions = db.scalars(query).all()
    prefix = _item_archive_prefix(item)
    manifest = []
    for index, revision in enumerate(revisions, start=1):
        filename = _revision_archive_name(
            prefix,
            index,
            revision.original_name,
            annotated=include_annotations,
        )
        source = store.path(revision.object_key)
        exported = source
        if include_annotations:
            annotated = temporary_root / f"{revision.id}.pdf"
            if _write_annotated_pdf(source, annotated, db, user, revision.id, timezone):
                exported = annotated
        archive_filename = _bundle_path(root, filename)
        bundle.write(exported, archive_filename)
        manifest.append({
            "version": index,
            "revision_id": revision.id,
            "original_name": revision.original_name,
            "filename": archive_filename,
            "created_at": revision.created_at.isoformat(),
            "processing_state": getattr(
                revision.processing_state, "value", revision.processing_state
            ),
        })
    bundle.writestr(
        _bundle_path(root, "manifest.json"),
        json.dumps({"pdf_revisions": manifest}, ensure_ascii=False, indent=2),
    )
    if include_supplements:
        attachments = db.scalars(
            select(Attachment).where(Attachment.item_id == item.id).order_by(Attachment.created_at)
        ).all()
        for index, attachment in enumerate(attachments, start=1):
            safe_name = _archive_name(
                Path(attachment.original_name).name, f"supplement-{index:02d}"
            )
            bundle.write(
                store.path(attachment.object_key),
                _bundle_path(root, f"supplements/{index:02d}-{safe_name}"),
            )
    return prefix


def create_item_document_bundle(
    db: Session,
    user: User,
    item_id: str,
    *,
    revision_ids: list[str] | None = None,
    include_annotations: bool = False,
    include_supplements: bool = False,
    timezone: str | None = None,
) -> ItemDownloadBundle:
    """Create a single-Item document bundle without changing source files."""
    item = require_accessible_items(db, user, [item_id])[0]
    archive = BytesIO()
    store = LocalObjectStore()
    prefix = _item_archive_prefix(item)
    with (
        TemporaryDirectory() as temporary_dir,
        zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle,
    ):
        temporary_root = Path(temporary_dir)
        _write_item_bundle_entries(
            bundle,
            db,
            user,
            item,
            store,
            temporary_root,
            revision_ids=revision_ids,
            include_annotations=include_annotations,
            include_supplements=include_supplements,
            timezone=timezone,
        )
    record_event(
        db,
        user.id,
        "item.download_bundle",
        "item",
        item.id,
        detail={
            "include_annotations": include_annotations,
            "include_supplements": include_supplements,
            "revision_ids": revision_ids or [],
        },
    )
    db.commit()
    archive.seek(0)
    kind = _download_kind(include_annotations, include_supplements)
    return ItemDownloadBundle(content=archive, filename=f"{prefix}-{kind}.zip")


def assemble_document_bundle(
    db: Session,
    user: User,
    items: list[Item],
    *,
    include_annotations: bool = False,
    include_supplements: bool = False,
    timezone: str | None = None,
) -> ItemDownloadBundle:
    """Assemble document archives for already-selected Items."""
    archive = BytesIO()
    store = LocalObjectStore()
    item_manifest = []
    used_roots: set[str] = set()
    with (
        TemporaryDirectory() as temporary_dir,
        zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle,
    ):
        temporary_root = Path(temporary_dir)
        for item in items:
            root = _item_archive_prefix(item)
            if root in used_roots:
                root = f"{root}-{item.id[:8]}"
            used_roots.add(root)
            _write_item_bundle_entries(
                bundle,
                db,
                user,
                item,
                store,
                temporary_root,
                root=root,
                include_annotations=include_annotations,
                include_supplements=include_supplements,
                timezone=timezone,
            )
            item_manifest.append({
                "item_id": item.id,
                "title": convert_rich_text(item.title, source="html", target="text"),
                "folder": root,
            })
        bundle.writestr(
            "manifest.json",
            json.dumps({"items": item_manifest}, ensure_ascii=False, indent=2),
        )
    archive.seek(0)
    kind = _download_kind(include_annotations, include_supplements)
    return ItemDownloadBundle(content=archive, filename=f"quirebase-selected-{kind}.zip")


def _record_revision_pdf_export(
    db: Session,
    user: User,
    item_id: str,
    revision_id: str,
    *,
    include_annotations: bool,
    project_id: str | None,
) -> None:
    record_event(
        db,
        user.id,
        "item.download_revision_pdf",
        "revision",
        revision_id,
        detail={
            "item_id": item_id,
            "include_annotations": include_annotations,
            "project_id": project_id,
        },
    )
    db.commit()


def export_revision_pdf(
    db: Session,
    user: User,
    item_id: str,
    revision_id: str,
    *,
    include_annotations: bool = True,
    project_id: str | None = None,
    timezone: str | None = None,
) -> tuple[Path, str, str, bool]:
    """Export a single FileRevision, optionally flattening annotations onto the PDF."""
    revision = require_revision(db, user, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    store = LocalObjectStore()
    source = store.path(revision.object_key)
    if not include_annotations:
        _record_revision_pdf_export(
            db,
            user,
            item_id,
            revision_id,
            include_annotations=include_annotations,
            project_id=project_id,
        )
        return source, revision.original_name, "application/pdf", False

    annotations = select_visible_annotations(db, user, revision.id, item_id, project_id)
    if not annotations:
        _record_revision_pdf_export(
            db,
            user,
            item_id,
            revision_id,
            include_annotations=include_annotations,
            project_id=project_id,
        )
        return source, revision.original_name, "application/pdf", False

    with NamedTemporaryFile(suffix=".pdf", delete=False) as target:
        target_path = Path(target.name)
    try:
        author_names = {user.id: user.username}
        if project_id:
            author_rows = db.execute(
                select(User.id, User.username).where(
                    User.id.in_({record.author_id for record in annotations})
                )
            ).all()
            author_names = {row[0]: row[1] for row in author_rows}
        export_annotations(
            source,
            target_path,
            annotations,
            author_names=author_names,
            display_timezone=annotation_export_timezone(timezone),
        )
        safe_name = _archive_name(Path(revision.original_name).stem, "document")
    except BaseException:
        target_path.unlink(missing_ok=True)
        raise
    try:
        _record_revision_pdf_export(
            db,
            user,
            item_id,
            revision_id,
            include_annotations=include_annotations,
            project_id=project_id,
        )
    except BaseException:
        target_path.unlink(missing_ok=True)
        raise
    return target_path, f"{safe_name}-annotated.pdf", "application/pdf", True
