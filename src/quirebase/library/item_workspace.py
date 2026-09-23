"""Open one Item and build the read model for its selected workspace section."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from quirebase.access import Capability, require_workspace_capability, role_has_capability
from quirebase.access.items import can_delete_item, can_edit_item, require_readable_item
from quirebase.core.errors import ResourceNotFound
from quirebase.library.authors import get_item_authors
from quirebase.library.item_metadata import ItemMetadata, metadata_from_item
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
    ProjectState,
    Tag,
    User,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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
    updater: User | None
    identifiers: tuple[ItemIdentifier, ...]


@dataclass(frozen=True)
class MetadataWorkspace(WorkspaceView):
    authors: tuple[ItemAuthor, ...]
    editors: tuple[ItemAuthor, ...]
    metadata: ItemMetadata


@dataclass(frozen=True)
class FilesWorkspace(WorkspaceView):
    attachments: tuple[Attachment, ...]


@dataclass(frozen=True)
class ProjectMembership:
    project: Project


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


async def _record_read(db: AsyncSession, user: User, workspace_id: str, item_id: str) -> None:
    read = await db.get(ItemRead, (user.id, item_id))
    if read is None:
        db.add(ItemRead(user_id=user.id, workspace_id=workspace_id, item_id=item_id))
    else:
        read.last_read_at = datetime.now(UTC)


async def _open_summary(db: AsyncSession, user: User, item: Item) -> SummaryWorkspace:
    context = await require_workspace_capability(
        db, user, item.workspace_id, Capability.workspace_read
    )
    moderator = role_has_capability(context.role, Capability.annotations_moderate)
    revisions = tuple(
        (
            await db.scalars(
                select(FileRevision)
                .where(
                    FileRevision.workspace_id == item.workspace_id,
                    FileRevision.item_id == item.id,
                )
                .order_by(FileRevision.created_at.desc())
            )
        ).all()
    )
    member_projects = select(ProjectMember.project_id).where(
        ProjectMember.workspace_id == item.workspace_id,
        ProjectMember.user_id == user.id,
    )
    visible_project_items = (
        select(ProjectItem.id)
        .join(Project, Project.id == ProjectItem.project_id)
        .where(
            ProjectItem.workspace_id == item.workspace_id,
            Project.state != ProjectState.deleted,
            (Project.visibility == "workspace") | Project.id.in_(member_projects),
        )
    )
    revision_ids = [revision.id for revision in revisions]
    annotation_count = 0
    if revision_ids:
        annotation_count = (
            await db.scalar(
                select(func.count(PdfAnnotation.id)).where(
                    PdfAnnotation.file_revision_id.in_(revision_ids),
                    PdfAnnotation.workspace_id == item.workspace_id,
                    PdfAnnotation.deleted_at.is_(None),
                    *(
                        ()
                        if moderator
                        else (
                            PdfAnnotation.hidden_at.is_(None),
                            PdfAnnotation.archived_at.is_(None),
                        )
                    ),
                    or_(
                        and_(
                            PdfAnnotation.scope == AnnotationScope.private,
                            PdfAnnotation.author_id == user.id,
                        ),
                        and_(
                            PdfAnnotation.scope == AnnotationScope.project,
                            PdfAnnotation.project_item_id.in_(visible_project_items),
                        ),
                    ),
                )
            )
            or 0
        )
    message_count = (
        await db.scalar(
            select(func.count(DiscussionMessage.id)).where(
                DiscussionMessage.workspace_id == item.workspace_id,
                DiscussionMessage.item_id == item.id,
            )
        )
        or 0
    )
    attachment_count = (
        await db.scalar(
            select(func.count(Attachment.id)).where(
                Attachment.workspace_id == item.workspace_id,
                Attachment.item_id == item.id,
            )
        )
        or 0
    )
    identifiers = tuple(
        (await db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item.id))).all()
    )
    tags = tuple(
        (
            await db.scalars(
                select(Tag)
                .join(ItemTag, ItemTag.tag_id == Tag.id)
                .where(
                    ItemTag.workspace_id == item.workspace_id,
                    ItemTag.item_id == item.id,
                    Tag.workspace_id == item.workspace_id,
                )
                .order_by(Tag.name)
            )
        ).all()
    )
    return SummaryWorkspace(
        item=item,
        can_edit=await can_edit_item(db, user, item.workspace_id, item.id),
        can_delete=await can_delete_item(db, user, item.workspace_id, item.id),
        revisions=revisions[:1],
        revision_count=len(revisions),
        attachment_count=attachment_count,
        annotation_count=annotation_count,
        message_count=message_count,
        tags=tags,
        updater=await db.get(User, item.updated_by) if item.updated_by else None,
        identifiers=identifiers,
    )


async def _revisions(
    db: AsyncSession, workspace_id: str, item_id: str, *, all_revisions: bool = False
) -> tuple[FileRevision, ...]:
    query = (
        select(FileRevision)
        .where(FileRevision.workspace_id == workspace_id, FileRevision.item_id == item_id)
        .order_by(FileRevision.created_at.desc())
    )
    if not all_revisions:
        query = query.limit(1)
    return tuple((await db.scalars(query)).all())


async def _open_metadata(db: AsyncSession, user: User, item: Item) -> MetadataWorkspace:
    authors = tuple(await get_item_authors(db, item.id, role="author"))
    editors = tuple(await get_item_authors(db, item.id, role="editor"))
    identifiers = tuple(
        (await db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item.id))).all()
    )
    return MetadataWorkspace(
        item=item,
        can_edit=await can_edit_item(db, user, item.workspace_id, item.id),
        can_delete=await can_delete_item(db, user, item.workspace_id, item.id),
        revisions=await _revisions(db, item.workspace_id, item.id),
        authors=authors,
        editors=editors,
        metadata=metadata_from_item(item, authors, editors, identifiers),
    )


async def _open_files(db: AsyncSession, user: User, item: Item) -> FilesWorkspace:
    attachments = tuple(
        (
            await db.scalars(
                select(Attachment)
                .where(
                    Attachment.workspace_id == item.workspace_id,
                    Attachment.item_id == item.id,
                )
                .order_by(Attachment.created_at)
            )
        ).all()
    )
    return FilesWorkspace(
        item=item,
        can_edit=await can_edit_item(db, user, item.workspace_id, item.id),
        can_delete=await can_delete_item(db, user, item.workspace_id, item.id),
        revisions=await _revisions(db, item.workspace_id, item.id, all_revisions=True),
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


async def _open_organize(db: AsyncSession, user: User, item: Item) -> OrganizeWorkspace:
    tags = tuple(
        (
            await db.scalars(
                select(Tag)
                .join(ItemTag, ItemTag.tag_id == Tag.id)
                .where(
                    ItemTag.workspace_id == item.workspace_id,
                    ItemTag.item_id == item.id,
                    Tag.workspace_id == item.workspace_id,
                )
                .order_by(Tag.name)
            )
        ).all()
    )
    membership_rows = (
        (
            await db.execute(
                select(Project)
                .outerjoin(
                    ProjectMember,
                    (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == user.id),
                )
                .where(
                    Project.workspace_id == item.workspace_id,
                    Project.state != ProjectState.deleted,
                    (Project.visibility == "workspace") | ProjectMember.id.is_not(None),
                )
                .order_by(Project.name)
            )
        )
        .scalars()
        .all()
    )
    memberships = tuple(ProjectMembership(project=row) for row in membership_rows)
    visible_project_ids = {membership.project.id for membership in memberships}
    assigned_project_ids = frozenset(
        (
            await db.scalars(
                select(ProjectItem.project_id).where(
                    ProjectItem.workspace_id == item.workspace_id,
                    ProjectItem.item_id == item.id,
                    ProjectItem.project_id.in_(visible_project_ids),
                )
            )
        ).all()
    )
    return OrganizeWorkspace(
        item=item,
        can_edit=await can_edit_item(db, user, item.workspace_id, item.id),
        can_delete=await can_delete_item(db, user, item.workspace_id, item.id),
        revisions=await _revisions(db, item.workspace_id, item.id),
        tags=tags,
        memberships=memberships,
        assigned_project_ids=assigned_project_ids,
        tag_matrix=_typed_tag_matrix(
            await get_tag_matrix_for_item(db, user, item.workspace_id, item.id)
        ),
    )


async def _open_annotations(db: AsyncSession, user: User, item: Item) -> AnnotationsWorkspace:
    context = await require_workspace_capability(
        db, user, item.workspace_id, Capability.workspace_read
    )
    moderator = role_has_capability(context.role, Capability.annotations_moderate)
    revisions = await _revisions(db, item.workspace_id, item.id, all_revisions=True)
    annotations: tuple[AnnotationView, ...] = ()
    if revisions:
        member_projects = select(ProjectMember.project_id).where(
            ProjectMember.workspace_id == item.workspace_id,
            ProjectMember.user_id == user.id,
        )
        visible_project_items = (
            select(ProjectItem.id)
            .join(Project, Project.id == ProjectItem.project_id)
            .where(
                ProjectItem.workspace_id == item.workspace_id,
                Project.state != ProjectState.deleted,
                (Project.visibility == "workspace") | Project.id.in_(member_projects),
            )
        )
        rows = (
            await db.execute(
                select(PdfAnnotation, FileRevision, User)
                .join(FileRevision, FileRevision.id == PdfAnnotation.file_revision_id)
                .join(User, User.id == PdfAnnotation.author_id)
                .where(
                    PdfAnnotation.file_revision_id.in_([revision.id for revision in revisions]),
                    PdfAnnotation.workspace_id == item.workspace_id,
                    PdfAnnotation.deleted_at.is_(None),
                    *(
                        ()
                        if moderator
                        else (
                            PdfAnnotation.hidden_at.is_(None),
                            PdfAnnotation.archived_at.is_(None),
                        )
                    ),
                    or_(
                        and_(
                            PdfAnnotation.scope == AnnotationScope.private,
                            PdfAnnotation.author_id == user.id,
                        ),
                        and_(
                            PdfAnnotation.scope == AnnotationScope.project,
                            PdfAnnotation.project_item_id.in_(visible_project_items),
                        ),
                    ),
                )
                .order_by(PdfAnnotation.updated_at.desc())
            )
        ).all()
        annotations = tuple(
            AnnotationView(annotation=row[0], revision=row[1], author=row[2]) for row in rows
        )
    return AnnotationsWorkspace(
        item=item,
        can_edit=await can_edit_item(db, user, item.workspace_id, item.id),
        can_delete=await can_delete_item(db, user, item.workspace_id, item.id),
        revisions=revisions,
        annotations=annotations,
    )


async def _open_discussion(db: AsyncSession, user: User, item: Item) -> DiscussionWorkspace:
    messages = tuple(
        (
            await db.scalars(
                select(DiscussionMessage)
                .options(selectinload(DiscussionMessage.author))
                .where(
                    DiscussionMessage.workspace_id == item.workspace_id,
                    DiscussionMessage.item_id == item.id,
                )
                .order_by(DiscussionMessage.created_at)
            )
        ).all()
    )
    return DiscussionWorkspace(
        item=item,
        can_edit=await can_edit_item(db, user, item.workspace_id, item.id),
        can_delete=await can_delete_item(db, user, item.workspace_id, item.id),
        revisions=await _revisions(db, item.workspace_id, item.id),
        messages=messages,
    )


async def open_item_workspace(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    section: WorkspaceSection,
) -> ItemWorkspace:
    try:
        item = await require_readable_item(db, user, workspace_id, item_id)
        view: ItemWorkspace
        match section:
            case WorkspaceSection.summary:
                view = await _open_summary(db, user, item)
            case WorkspaceSection.metadata:
                view = await _open_metadata(db, user, item)
            case WorkspaceSection.files:
                view = await _open_files(db, user, item)
            case WorkspaceSection.organize:
                view = await _open_organize(db, user, item)
            case WorkspaceSection.annotations:
                view = await _open_annotations(db, user, item)
            case WorkspaceSection.discussion:
                view = await _open_discussion(db, user, item)
        await _record_read(db, user, workspace_id, item.id)
        await db.commit()
        return view
    except Exception:
        await db.rollback()
        raise
