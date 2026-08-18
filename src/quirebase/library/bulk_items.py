"""Apply one operation to a user-selected set of Items."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from quirebase.access.items import (
    can_edit_item,
    require_accessible_items,
)
from quirebase.access.projects import project_member
from quirebase.audit import record_event
from quirebase.core.errors import (
    PermissionDenied,
    ValidationFailure,
)
from quirebase.core.storage import LocalObjectStore
from quirebase.library.tags import get_or_create_tag
from quirebase.models import (
    Attachment,
    FileRevision,
    Item,
    ItemTag,
    PdfAnnotation,
    ProjectItem,
    User,
)
from quirebase.pipeline.inspection import export_annotations
from quirebase.search import search_index


@dataclass(frozen=True)
class ItemDownloadBundle:
    content: BytesIO
    filename: str


def _archive_name(value: str, fallback: str) -> str:
    name = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-.")
    return (name or fallback)[:80]


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
    include_annotations: bool = False,
    include_supplements: bool = False,
) -> str:
    revisions = db.scalars(
        select(FileRevision)
        .where(FileRevision.item_id == item.id)
        .order_by(FileRevision.created_at.desc())
    ).all()
    prefix = _archive_name(item.bibtex_id or item.title, item.id[:8])
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
            annotations = list(
                db.scalars(
                    select(PdfAnnotation)
                    .options(selectinload(PdfAnnotation.segments))
                    .where(
                        PdfAnnotation.file_revision_id == revision.id,
                        PdfAnnotation.author_id == user.id,
                        PdfAnnotation.deleted_at.is_(None),
                    )
                    .order_by(PdfAnnotation.created_at)
                ).all()
            )
            if annotations:
                exported = temporary_root / f"{revision.id}.pdf"
                export_annotations(
                    source,
                    exported,
                    annotations,
                    author_names={user.id: user.username},
                )
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


def download_item_pdfs(
    db: Session,
    user: User,
    item_ids: list[str],
    *,
    include_annotations: bool = False,
    include_supplements: bool = False,
) -> ItemDownloadBundle:
    items = require_accessible_items(db, user, item_ids)
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
            root = _archive_name(item.bibtex_id or item.title, item.id[:8])
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
            )
            item_manifest.append({"item_id": item.id, "title": item.title, "folder": root})
        bundle.writestr(
            "manifest.json",
            json.dumps({"items": item_manifest}, ensure_ascii=False, indent=2),
        )
    record_event(
        db,
        user.id,
        "library.bulk.download_pdfs",
        "item",
        None,
        detail={
            "item_ids": [item.id for item in items],
            "include_annotations": include_annotations,
            "include_supplements": include_supplements,
        },
    )
    db.commit()
    archive.seek(0)
    kind = _download_kind(include_annotations, include_supplements)
    return ItemDownloadBundle(content=archive, filename=f"quirebase-selected-{kind}.zip")


def download_item_bundle(
    db: Session,
    user: User,
    item_id: str,
    *,
    include_annotations: bool = False,
    include_supplements: bool = False,
) -> ItemDownloadBundle:
    """Create a single-Item download bundle without changing source files."""
    item = require_accessible_items(db, user, [item_id])[0]
    archive = BytesIO()
    store = LocalObjectStore()
    prefix = _archive_name(item.bibtex_id or item.title, item.id[:8])
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
            include_annotations=include_annotations,
            include_supplements=include_supplements,
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
        },
    )
    db.commit()
    archive.seek(0)
    kind = _download_kind(include_annotations, include_supplements)
    return ItemDownloadBundle(content=archive, filename=f"{prefix}-{kind}.zip")


def apply_bulk_item_action(
    db: Session,
    user: User,
    item_ids: list[str],
    action: str,
    project_id: str = "",
    tag_name: str = "",
    confirm_delete: str = "",
) -> list[str]:
    items = require_accessible_items(db, user, item_ids)

    # Fail-closed: All selected items must be editable for mutating bulk actions
    if any(not can_edit_item(db, user, item.id) for item in items):
        raise PermissionDenied("all selected items must be editable")

    cleanup_keys: list[str] = []
    if action in ("add_project", "project_add"):
        membership = project_member(db, user, project_id)
        if membership is None or membership.role not in ("owner", "editor"):
            raise ValidationFailure("choose an editable project")
        for item in items:
            if db.get(ProjectItem, (project_id, item.id)) is None:
                db.add(ProjectItem(project_id=project_id, item_id=item.id))
                search_index(db).index_item(db, item.id)
        audit_action = "library.bulk.add_project"
    elif action in ("add_tag", "tag"):
        tag_record = get_or_create_tag(db, user, tag_name)
        for item in items:
            if db.get(ItemTag, (item.id, tag_record.id)) is None:
                db.add(ItemTag(item_id=item.id, tag_id=tag_record.id))
                search_index(db).index_item(db, item.id)
        audit_action = "library.bulk.add_tag"
    elif action in ("delete_items", "delete"):
        if confirm_delete != "delete":
            raise ValidationFailure("confirm deletion of the selected items")
        if user.role != "administrator" and any(item.created_by != user.id for item in items):
            raise PermissionDenied("only item owners can permanently delete items")
        cleanup_keys = list(
            db.scalars(
                select(FileRevision.object_key).where(
                    FileRevision.item_id.in_([item.id for item in items])
                )
            ).all()
        )
        cleanup_keys.extend(
            db.scalars(
                select(Attachment.object_key).where(
                    Attachment.item_id.in_([item.id for item in items])
                )
            ).all()
        )
        for item in items:
            search_index(db).remove_item(db, item.id)
            db.delete(item)
        audit_action = "library.bulk.delete_items"
    else:
        raise ValidationFailure("unknown bulk action")

    record_event(
        db,
        user.id,
        audit_action,
        "item",
        None,
        detail={"item_ids": [item.id for item in items]},
    )
    db.commit()

    for object_key in cleanup_keys:
        with Session(db.bind) as cleanup_db:
            still_used = cleanup_db.scalar(
                select(FileRevision.id).where(FileRevision.object_key == object_key).limit(1)
            ) or cleanup_db.scalar(
                select(Attachment.id).where(Attachment.object_key == object_key).limit(1)
            )
        if not still_used:
            LocalObjectStore().delete(object_key)

    return cleanup_keys
