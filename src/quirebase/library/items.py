from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from quirebase.access.items import (
    can_edit_item,
    require_accessible_items,
    require_editable_item,
    require_readable_item,
)
from quirebase.access.projects import project_member
from quirebase.core.errors import (
    PermissionDenied,
    ResourceNotFound,
    ValidationFailure,
    VersionConflict,
)
from quirebase.core.storage import LocalObjectStore
from quirebase.library.audit import record_audit_event
from quirebase.library.authors import parse_author_name, set_item_authors
from quirebase.library.identifiers import set_item_identifiers
from quirebase.library.tags import get_tag_matrix_for_item
from quirebase.models import (
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


def create_item(
    db: Session,
    user: User,
    *,
    title: str,
    abstract: str = "",
    authors: str = "",
) -> Item:
    if not title.strip():
        raise ValidationFailure("title is required")
    item = Item(
        title=title.strip(),
        abstract=abstract.strip() or None,
        authors=authors.strip() or None,
        created_by=user.id,
    )
    db.add(item)
    db.flush()
    if item.authors:
        parsed_authors = []
        for raw in item.authors.split(";"):
            if raw.strip():
                last, first = parse_author_name(raw.strip())
                parsed_authors.append({"last_name": last, "first_name": first})
        if parsed_authors:
            set_item_authors(db, user, item.id, parsed_authors, role="author")
    search_index(db).index_item(db, item.id)
    record_audit_event(db, user.id, "item.create", "item", item.id)
    db.commit()
    return item


def update_item(
    db: Session,
    user: User,
    *,
    item_id: str,
    version: int,
    title: str,
    abstract: str = "",
    authors: str = "",
    editors: str = "",
    keywords: str = "",
    publication_date: str = "",
    publication_title: str = "",
    doi: str = "",
    reference_type: str = "",
    volume: str = "",
    issue: str = "",
    pages: str = "",
    affiliation: str = "",
    publisher: str = "",
    place_published: str = "",
    journal_abbreviation: str = "",
    bibtex_id: str = "",
    bibtex_type: str = "",
    urls: str = "",
    identifiers: str = "",
    custom_fields: str = "",
) -> Item:
    require_editable_item(db, user, item_id)
    if not title.strip():
        raise ValidationFailure("title is required")
    parsed_identifiers: dict[str, Any] | None = None
    if identifiers.strip():
        try:
            parsed_identifiers = json.loads(identifiers)
        except json.JSONDecodeError as error:
            raise ValidationFailure("identifiers must be valid JSON") from error
        if not isinstance(parsed_identifiers, dict):
            raise ValidationFailure("identifiers must be a JSON object")
    parsed_custom: dict[str, Any] | None = None
    if custom_fields.strip():
        try:
            parsed_custom = json.loads(custom_fields)
        except json.JSONDecodeError as error:
            raise ValidationFailure("custom fields must be valid JSON") from error
        if not isinstance(parsed_custom, dict):
            raise ValidationFailure("custom fields must be a JSON object")

    updated_id = db.scalar(
        update(Item)
        .where(Item.id == item_id, Item.version == version)
        .values(
            title=title.strip(),
            abstract=abstract.strip() or None,
            authors=authors.strip() or None,
            editors=editors.strip() or None,
            keywords=keywords.strip() or None,
            publication_date=publication_date.strip() or None,
            publication_title=publication_title.strip() or None,
            doi=doi.strip() or None,
            reference_type=reference_type.strip() or None,
            volume=volume.strip() or None,
            issue=issue.strip() or None,
            pages=pages.strip() or None,
            affiliation=affiliation.strip() or None,
            publisher=publisher.strip() or None,
            place_published=place_published.strip() or None,
            journal_abbreviation=journal_abbreviation.strip() or None,
            bibtex_id=bibtex_id.strip() or None,
            bibtex_type=bibtex_type.strip() or None,
            urls=urls.strip() or None,
            identifiers=json.dumps(parsed_identifiers, ensure_ascii=False)
            if parsed_identifiers is not None
            else None,
            custom_fields=json.dumps(parsed_custom, ensure_ascii=False)
            if parsed_custom is not None
            else None,
            updated_by=user.id,
            version=Item.version + 1,
            updated_at=datetime.now(UTC),
        )
        .returning(Item.id)
    )
    if updated_id is None:
        db.rollback()
        current = db.get(Item, item_id)
        raise VersionConflict(current.version if current else None)
    db.flush()
    db.expire_all()
    item = db.get(Item, item_id)
    if item is None:
        raise ResourceNotFound("item not found")
    search_index(db).index_item(db, item.id)
    record_audit_event(
        db,
        user.id,
        "item.update",
        "item",
        item.id,
        detail={"version": version + 1},
    )
    db.commit()
    return item


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
    mark_item_read(db, user, item_id)

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
                                PdfAnnotation.scope == "private",
                                PdfAnnotation.author_id == user.id,
                            ),
                            and_(
                                PdfAnnotation.scope == "project",
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
                            PdfAnnotation.scope == "private",
                            PdfAnnotation.author_id == user.id,
                        ),
                        and_(
                            PdfAnnotation.scope == "project",
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

    creator = db.get(User, item.created_by) if item.created_by else None
    updater = db.get(User, item.updated_by) if item.updated_by else None
    identifier_links = list(
        db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item_id)).all()
    )
    if not identifier_links and item.doi and item.doi.strip() and can_edit:
        set_item_identifiers(db, user, item_id, [("doi", item.doi.strip())])
        db.commit()
        identifier_links = list(
            db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item_id)).all()
        )

    author_links = list(
        db.scalars(
            select(ItemAuthor)
            .options(selectinload(ItemAuthor.author))
            .where(ItemAuthor.item_id == item_id, ItemAuthor.role == "author")
            .order_by(ItemAuthor.position)
        ).all()
    )
    if not author_links and item.authors and item.authors.strip() and can_edit:
        parsed_authors = []
        for raw in item.authors.split(";"):
            if raw.strip():
                last, first = parse_author_name(raw.strip())
                parsed_authors.append({"last_name": last, "first_name": first})
        if parsed_authors:
            author_links = set_item_authors(db, user, item_id, parsed_authors, role="author")
            db.commit()

    editor_links = list(
        db.scalars(
            select(ItemAuthor)
            .options(selectinload(ItemAuthor.author))
            .where(ItemAuthor.item_id == item_id, ItemAuthor.role == "editor")
            .order_by(ItemAuthor.position)
        ).all()
    )
    if not editor_links and item.editors and item.editors.strip() and can_edit:
        parsed_editors = []
        for raw in item.editors.split(";"):
            if raw.strip():
                last, first = parse_author_name(raw.strip())
                parsed_editors.append({"last_name": last, "first_name": first})
        if parsed_editors:
            editor_links = set_item_authors(db, user, item_id, parsed_editors, role="editor")
            db.commit()

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
    record_audit_event(
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
        normalized = " ".join(tag_name.split())
        if not normalized or len(normalized) > 120:
            raise ValidationFailure("enter a tag containing 1 to 120 characters")
        tag_record = db.scalar(select(Tag).where(Tag.name == normalized))
        if tag_record is None:
            tag_record = Tag(name=normalized, created_by=user.id)
            db.add(tag_record)
            db.flush()
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

    record_audit_event(
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
