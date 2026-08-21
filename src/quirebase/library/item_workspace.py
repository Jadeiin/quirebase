"""Open one Item and build the read model for its selected workspace section."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from quirebase.access.items import can_delete_item, can_edit_item, require_readable_item
from quirebase.core.errors import ResourceNotFound
from quirebase.library.authors import get_item_authors
from quirebase.library.tags import get_tag_matrix_for_item
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
    ProjectRole,
    Tag,
    User,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class WorkspaceSection(StrEnum):
    summary = "summary"
    metadata = "metadata"
    files = "files"
    organize = "organize"
    annotations = "annotations"
    discussion = "discussion"

    @classmethod
    def parse(cls, value: str) -> WorkspaceSection:
        try:
            return cls(value)
        except ValueError as error:
            raise ResourceNotFound(f"unknown item section: {value}") from error


@dataclass(frozen=True)
class WorkspaceView:
    item: Item
    can_edit: bool
    can_delete: bool
    revisions: tuple[FileRevision, ...]


@dataclass(frozen=True)
class SummaryWorkspace(WorkspaceView):
    revision_count: int
    attachment_count: int
    annotation_count: int
    message_count: int
    tags: tuple[Tag, ...]
    item_owner: User
    updater: User | None
    identifiers: tuple[ItemIdentifier, ...]


@dataclass(frozen=True)
class MetadataWorkspace(WorkspaceView):
    authors: tuple[ItemAuthor, ...]
    editors: tuple[ItemAuthor, ...]


@dataclass(frozen=True)
class FilesWorkspace(WorkspaceView):
    attachments: tuple[Attachment, ...]


@dataclass(frozen=True)
class ProjectMembership:
    project: Project
    role: ProjectRole


@dataclass(frozen=True)
class TagGroup:
    letter: str
    tags: tuple[Tag, ...]
    names: tuple[str, ...]


@dataclass(frozen=True)
class TagMatrix:
    groups: tuple[TagGroup, ...]
    assigned_ids: frozenset[str]
    recommended_ids: frozenset[str]
    suggested_names: tuple[str, ...]
    suggested_single_words: tuple[str, ...]
    suggested_phrases: tuple[str, ...]
    recommendation_state: str
    recommendation_error: str | None


@dataclass(frozen=True)
class OrganizeWorkspace(WorkspaceView):
    tags: tuple[Tag, ...]
    memberships: tuple[ProjectMembership, ...]
    assigned_project_ids: frozenset[str]
    tag_matrix: TagMatrix


@dataclass(frozen=True)
class AnnotationView:
    annotation: PdfAnnotation
    revision: FileRevision
    author: User


@dataclass(frozen=True)
class AnnotationsWorkspace(WorkspaceView):
    annotations: tuple[AnnotationView, ...]


@dataclass(frozen=True)
class DiscussionWorkspace(WorkspaceView):
    messages: tuple[DiscussionMessage, ...]


type ItemWorkspace = (
    SummaryWorkspace
    | MetadataWorkspace
    | FilesWorkspace
    | OrganizeWorkspace
    | AnnotationsWorkspace
    | DiscussionWorkspace
)


def _record_read(db: Session, user: User, item_id: str) -> None:
    read = db.get(ItemRead, (user.id, item_id))
    if read is None:
        db.add(ItemRead(user_id=user.id, item_id=item_id))
    else:
        read.last_read_at = datetime.now(UTC)


def _open_summary(db: Session, user: User, item: Item) -> SummaryWorkspace:
    revisions = tuple(
        db.scalars(
            select(FileRevision)
            .where(FileRevision.item_id == item.id)
            .order_by(FileRevision.created_at.desc())
        ).all()
    )
    member_projects = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    revision_ids = [revision.id for revision in revisions]
    annotation_count = 0
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
            select(func.count(DiscussionMessage.id)).where(DiscussionMessage.item_id == item.id)
        )
        or 0
    )
    attachment_count = (
        db.scalar(select(func.count(Attachment.id)).where(Attachment.item_id == item.id)) or 0
    )
    item_owner = db.get(User, item.created_by)
    if item_owner is None:
        raise ResourceNotFound("item owner not found")
    identifiers = tuple(
        db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item.id)).all()
    )
    tags = tuple(
        db.scalars(
            select(Tag)
            .join(ItemTag, ItemTag.tag_id == Tag.id)
            .where(ItemTag.item_id == item.id)
            .order_by(Tag.name)
        ).all()
    )
    return SummaryWorkspace(
        item=item,
        can_edit=can_edit_item(db, user, item.id),
        can_delete=can_delete_item(db, user, item),
        revisions=revisions[:1],
        revision_count=len(revisions),
        attachment_count=attachment_count,
        annotation_count=annotation_count,
        message_count=message_count,
        tags=tags,
        item_owner=item_owner,
        updater=db.get(User, item.updated_by) if item.updated_by else None,
        identifiers=identifiers,
    )


def _revisions(
    db: Session, item_id: str, *, all_revisions: bool = False
) -> tuple[FileRevision, ...]:
    query = (
        select(FileRevision)
        .where(FileRevision.item_id == item_id)
        .order_by(FileRevision.created_at.desc())
    )
    if not all_revisions:
        query = query.limit(1)
    return tuple(db.scalars(query).all())


def _open_metadata(db: Session, user: User, item: Item) -> MetadataWorkspace:
    return MetadataWorkspace(
        item=item,
        can_edit=can_edit_item(db, user, item.id),
        can_delete=can_delete_item(db, user, item),
        revisions=_revisions(db, item.id),
        authors=tuple(get_item_authors(db, item.id, role="author")),
        editors=tuple(get_item_authors(db, item.id, role="editor")),
    )


def _open_files(db: Session, user: User, item: Item) -> FilesWorkspace:
    attachments = tuple(
        db.scalars(
            select(Attachment).where(Attachment.item_id == item.id).order_by(Attachment.created_at)
        ).all()
    )
    return FilesWorkspace(
        item=item,
        can_edit=can_edit_item(db, user, item.id),
        can_delete=can_delete_item(db, user, item),
        revisions=_revisions(db, item.id, all_revisions=True),
        attachments=attachments,
    )


def _typed_tag_matrix(raw: dict[str, Any]) -> TagMatrix:
    raw_groups = cast("list[dict[str, Any]]", raw["groups"])
    return TagMatrix(
        groups=tuple(
            TagGroup(
                letter=str(group["letter"]),
                tags=tuple(cast("list[Tag]", group["tags"])),
                names=tuple(cast("list[str]", group["names"])),
            )
            for group in raw_groups
        ),
        assigned_ids=frozenset(cast("set[str]", raw["assigned_ids"])),
        recommended_ids=frozenset(cast("set[str]", raw["recommended_ids"])),
        suggested_names=tuple(cast("tuple[str, ...]", raw["suggested_names"])),
        suggested_single_words=tuple(cast("tuple[str, ...]", raw["suggested_single_words"])),
        suggested_phrases=tuple(cast("tuple[str, ...]", raw["suggested_phrases"])),
        recommendation_state=str(raw["recommendation_state"]),
        recommendation_error=(
            str(raw["recommendation_error"]) if raw["recommendation_error"] else None
        ),
    )


def _open_organize(db: Session, user: User, item: Item) -> OrganizeWorkspace:
    tags = tuple(
        db.scalars(
            select(Tag)
            .join(ItemTag, ItemTag.tag_id == Tag.id)
            .where(ItemTag.item_id == item.id)
            .order_by(Tag.name)
        ).all()
    )
    membership_rows = db.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user.id)
        .order_by(Project.name)
    ).all()
    memberships = tuple(ProjectMembership(project=row[0], role=row[1]) for row in membership_rows)
    assigned_project_ids = frozenset(
        db.scalars(select(ProjectItem.project_id).where(ProjectItem.item_id == item.id)).all()
    )
    return OrganizeWorkspace(
        item=item,
        can_edit=can_edit_item(db, user, item.id),
        can_delete=can_delete_item(db, user, item),
        revisions=_revisions(db, item.id),
        tags=tags,
        memberships=memberships,
        assigned_project_ids=assigned_project_ids,
        tag_matrix=_typed_tag_matrix(get_tag_matrix_for_item(db, user, item.id)),
    )


def _open_annotations(db: Session, user: User, item: Item) -> AnnotationsWorkspace:
    revisions = _revisions(db, item.id, all_revisions=True)
    annotations: tuple[AnnotationView, ...] = ()
    if revisions:
        member_projects = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
        rows = db.execute(
            select(PdfAnnotation, FileRevision, User)
            .join(FileRevision, FileRevision.id == PdfAnnotation.file_revision_id)
            .join(User, User.id == PdfAnnotation.author_id)
            .where(
                PdfAnnotation.file_revision_id.in_([revision.id for revision in revisions]),
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
        annotations = tuple(
            AnnotationView(annotation=row[0], revision=row[1], author=row[2]) for row in rows
        )
    return AnnotationsWorkspace(
        item=item,
        can_edit=can_edit_item(db, user, item.id),
        can_delete=can_delete_item(db, user, item),
        revisions=revisions,
        annotations=annotations,
    )


def _open_discussion(db: Session, user: User, item: Item) -> DiscussionWorkspace:
    messages = tuple(
        db.scalars(
            select(DiscussionMessage)
            .options(selectinload(DiscussionMessage.author))
            .where(DiscussionMessage.item_id == item.id)
            .order_by(DiscussionMessage.created_at)
        ).all()
    )
    return DiscussionWorkspace(
        item=item,
        can_edit=can_edit_item(db, user, item.id),
        can_delete=can_delete_item(db, user, item),
        revisions=_revisions(db, item.id),
        messages=messages,
    )


def open_item_workspace(
    db: Session,
    user: User,
    item_id: str,
    section: WorkspaceSection,
) -> ItemWorkspace:
    try:
        item = require_readable_item(db, user, item_id)
        view: ItemWorkspace
        match section:
            case WorkspaceSection.summary:
                view = _open_summary(db, user, item)
            case WorkspaceSection.metadata:
                view = _open_metadata(db, user, item)
            case WorkspaceSection.files:
                view = _open_files(db, user, item)
            case WorkspaceSection.organize:
                view = _open_organize(db, user, item)
            case WorkspaceSection.annotations:
                view = _open_annotations(db, user, item)
            case WorkspaceSection.discussion:
                view = _open_discussion(db, user, item)
        _record_read(db, user, item.id)
        db.commit()
        return view
    except Exception:
        db.rollback()
        raise
