from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from quirebase.access.items import (
    can_edit_item,
    require_accessible_items,
    require_readable_item,
)
from quirebase.access.projects import project_member
from quirebase.audit import record_event
from quirebase.core.errors import (
    PermissionDenied,
    ResourceNotFound,
    ValidationFailure,
)
from quirebase.core.storage import LocalObjectStore
from quirebase.library.authors import (
    get_item_authors,
)
from quirebase.library.tags import get_or_create_tag, get_tag_matrix_for_item
from quirebase.models import (
    AnnotationScope,
    Attachment,
    DiscussionMessage,
    FileRevision,
    Item,
    ItemAuthor,
    ItemIdentifier,
    ItemRead,
    ItemTag,
    PdfAnnotation,
    Project,
    ProjectItem,
    ProjectMember,
    Tag,
    User,
)
from quirebase.search import search_index


def mark_item_read(db: Session, user: User, item_id: str) -> None:
    read = db.get(ItemRead, (user.id, item_id))
    if read is None:
        db.add(ItemRead(user_id=user.id, item_id=item_id))
    else:
        read.last_read_at = datetime.now(UTC)
    db.commit()


def get_item_workspace_data(db: Session, user: User, item_id: str, section: str) -> dict[str, Any]:
    sections = {"summary", "metadata", "files", "organize", "annotations", "discussion"}
    if section not in sections:
        raise ResourceNotFound(f"unknown item section: {section}")
    require_readable_item(db, user, item_id)

    item = db.get(Item, item_id)
    if item is None:
        raise ResourceNotFound("item not found")

    can_edit = can_edit_item(db, user, item_id)

    # Base workspace data with lazy defaults
    revisions = list(
        db.scalars(
            select(FileRevision)
            .where(FileRevision.item_id == item_id)
            .order_by(FileRevision.created_at.desc())
            .limit(1)
        ).all()
    )
    revision_count = len(revisions)
    annotation_count = 0
    message_count = 0
    memberships: Any = ()
    assigned: set[str] = set()
    tags: list[Tag] = []
    messages: Any = ()
    attachments: list[Attachment] = []
    annotations: Any = ()
    creator: User | None = None
    updater: User | None = None
    identifier_links: list[ItemIdentifier] = []
    author_links: list[ItemAuthor] = []
    editor_links: list[ItemAuthor] = []

    if section in ("files", "annotations"):
        revisions = list(
            db.scalars(
                select(FileRevision)
                .where(FileRevision.item_id == item_id)
                .order_by(FileRevision.created_at.desc())
            ).all()
        )
        revision_count = len(revisions)

    if section == "summary":
        revision_ids = list(
            db.scalars(select(FileRevision.id).where(FileRevision.item_id == item_id)).all()
        )
        revision_count = len(revision_ids)
        member_projects = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
        if revision_ids:
            annotation_count = (
                db.scalar(
                    select(func.count(PdfAnnotation.id)).where(
                        PdfAnnotation.file_revision_id.in_(revision_ids),
                        PdfAnnotation.deleted_at.is_(None),
                        or_(
                            and_(
                                PdfAnnotation.scope == AnnotationScope.private,
                                PdfAnnotation.author_id == user.id,
                            ),
                            and_(
                                PdfAnnotation.scope == AnnotationScope.project,
                                PdfAnnotation.project_id.in_(member_projects),
                            ),
                        ),
                    )
                )
                or 0
            )
        message_count = (
            db.scalar(
                select(func.count(DiscussionMessage.id)).where(DiscussionMessage.item_id == item_id)
            )
            or 0
        )
        creator = db.get(User, item.created_by) if item.created_by else None
        updater = db.get(User, item.updated_by) if item.updated_by else None
        identifier_links = list(
            db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item_id)).all()
        )

    elif section == "metadata":
        author_links = get_item_authors(db, item_id, role="author")
        editor_links = get_item_authors(db, item_id, role="editor")

    elif section == "files":
        attachments = list(
            db.scalars(
                select(Attachment)
                .where(Attachment.item_id == item_id)
                .order_by(Attachment.created_at)
            ).all()
        )

    elif section == "organize":
        tags = list(
            db.scalars(
                select(Tag)
                .join(ItemTag, ItemTag.tag_id == Tag.id)
                .where(ItemTag.item_id == item_id)
                .order_by(Tag.name)
            ).all()
        )
        memberships = db.execute(
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id)
            .order_by(Project.name)
        ).all()
        assigned = set(
            db.scalars(select(ProjectItem.project_id).where(ProjectItem.item_id == item_id)).all()
        )

    elif section == "annotations":
        if revisions:
            member_projects = select(ProjectMember.project_id).where(
                ProjectMember.user_id == user.id
            )
            annotations = db.execute(
                select(PdfAnnotation, FileRevision, User)
                .join(FileRevision, FileRevision.id == PdfAnnotation.file_revision_id)
                .join(User, User.id == PdfAnnotation.author_id)
                .where(
                    PdfAnnotation.file_revision_id.in_([r.id for r in revisions]),
                    PdfAnnotation.deleted_at.is_(None),
                    or_(
                        and_(
                            PdfAnnotation.scope == AnnotationScope.private,
                            PdfAnnotation.author_id == user.id,
                        ),
                        and_(
                            PdfAnnotation.scope == AnnotationScope.project,
                            PdfAnnotation.project_id.in_(member_projects),
                        ),
                    ),
                )
                .order_by(PdfAnnotation.updated_at.desc())
            ).all()
            annotation_count = len(annotations)

    elif section == "discussion":
        messages = list(
            db.scalars(
                select(DiscussionMessage)
                .options(selectinload(DiscussionMessage.author))
                .where(DiscussionMessage.item_id == item_id)
                .order_by(DiscussionMessage.created_at)
            ).all()
        )
        message_count = len(messages)

    tag_matrix = get_tag_matrix_for_item(db, user, item_id) if section == "organize" else None

    return {
        "item": item,
        "revisions": revisions,
        "revision_count": revision_count,
        "memberships": memberships,
        "assigned": assigned,
        "tags": tags,
        "tag_matrix": tag_matrix,
        "messages": messages,
        "attachments": attachments,
        "annotations": annotations,
        "annotation_count": annotation_count,
        "message_count": message_count,
        "can_edit": can_edit,
        "creator": creator,
        "updater": updater,
        "identifier_links": identifier_links,
        "author_links": author_links,
        "editor_links": editor_links,
    }


def bulk_download_pdfs(db: Session, user: User, item_ids: list[str]) -> BytesIO:
    items = require_accessible_items(db, user, item_ids)
    archive = BytesIO()
    used_names: set[str] = set()
    store = LocalObjectStore()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for item in items:
            revision = db.scalar(
                select(FileRevision)
                .where(FileRevision.item_id == item.id)
                .order_by(FileRevision.created_at.desc())
                .limit(1)
            )
            if revision is None:
                continue
            filename = Path(revision.original_name).name
            if filename in used_names:
                filename = f"{item.id[:8]}-{filename}"
            used_names.add(filename)
            bundle.write(store.path(revision.object_key), filename)
    record_event(
        db,
        user.id,
        "library.bulk.download_pdfs",
        "item",
        None,
        detail={"item_ids": [item.id for item in items]},
    )
    db.commit()
    archive.seek(0)
    return archive


def bulk_action(
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
