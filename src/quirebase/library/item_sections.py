"""Open one Item section and build its section-specific read model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from quirebase.access import (
    ResourceAction,
    WorkspaceContext,
    action_allowed,
    get_item,
    require_action,
    visible_annotation_scope_predicate,
    visible_project_ids_query,
)
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.library.authors import get_item_authors
from quirebase.library.item_metadata import ItemMetadata, metadata_from_item
from quirebase.library.tags import TagMatrix, get_tag_matrix_for_item
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
    ProjectParticipation,
    ProjectState,
    Tag,
    User,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ItemSection(StrEnum):
    overview = "overview"
    metadata = "metadata"
    files = "files"
    organize = "organize"
    annotations = "annotations"
    discussion = "discussion"

    @classmethod
    def parse(cls, value: str) -> ItemSection:
        try:
            return cls(value)
        except ValueError as error:
            raise ResourceNotFound(f"unknown item section: {value}") from error


@dataclass(frozen=True)
class ItemSectionData:
    item: Item
    revisions: tuple[FileRevision, ...]


@dataclass(frozen=True)
class ItemOverviewData(ItemSectionData):
    revision_count: int
    attachment_count: int
    annotation_count: int
    message_count: int
    tags: tuple[Tag, ...]
    updater: User | None
    identifiers: tuple[ItemIdentifier, ...]


@dataclass(frozen=True)
class ItemMetadataData(ItemSectionData):
    authors: tuple[ItemAuthor, ...]
    editors: tuple[ItemAuthor, ...]
    metadata: ItemMetadata


@dataclass(frozen=True)
class ItemFilesData(ItemSectionData):
    attachments: tuple[Attachment, ...]


@dataclass(frozen=True)
class ProjectAssignmentOption:
    project: Project
    is_participating: bool


@dataclass(frozen=True)
class ItemOrganizationData(ItemSectionData):
    tags: tuple[Tag, ...]
    projects: tuple[ProjectAssignmentOption, ...]
    assigned_project_ids: frozenset[str]
    tag_matrix: TagMatrix


@dataclass(frozen=True)
class AnnotationView:
    annotation: PdfAnnotation
    revision: FileRevision
    author: User


@dataclass(frozen=True)
class ItemAnnotationsData(ItemSectionData):
    annotations: tuple[AnnotationView, ...]


@dataclass(frozen=True)
class ItemDiscussionData(ItemSectionData):
    messages: tuple[DiscussionMessage, ...]


type ItemSectionResult = (
    ItemOverviewData
    | ItemMetadataData
    | ItemFilesData
    | ItemOrganizationData
    | ItemAnnotationsData
    | ItemDiscussionData
)


async def _record_read(db: AsyncSession, user: User, workspace_id: str, item_id: str) -> None:
    read = await db.get(ItemRead, (user.id, item_id))
    if read is None:
        db.add(ItemRead(user_id=user.id, workspace_id=workspace_id, item_id=item_id))
    else:
        read.last_read_at = datetime.now(UTC)


async def _assigned_tags(db: AsyncSession, item: Item) -> tuple[Tag, ...]:
    return tuple(
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


async def _open_overview(
    db: AsyncSession, context: WorkspaceContext, item: Item
) -> ItemOverviewData:
    moderator = action_allowed(context, ResourceAction.project_annotation_review)
    revisions = await _revisions(db, item.workspace_id, item.id, all_revisions=True)
    visible_project_items = (
        select(ProjectItem.id)
        .join(Project, Project.id == ProjectItem.project_id)
        .where(
            ProjectItem.workspace_id == item.workspace_id,
            Project.state != ProjectState.deleted,
            Project.id.in_(visible_project_ids_query(context)),
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
                    visible_annotation_scope_predicate(
                        context,
                        project_item_ids=visible_project_items,
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
    tags = await _assigned_tags(db, item)
    return ItemOverviewData(
        item=item,
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


async def _open_metadata(
    db: AsyncSession, context: WorkspaceContext, item: Item
) -> ItemMetadataData:
    authors = tuple(await get_item_authors(db, item.id, role="author"))
    editors = tuple(await get_item_authors(db, item.id, role="editor"))
    identifiers = tuple(
        (await db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item.id))).all()
    )
    return ItemMetadataData(
        item=item,
        revisions=await _revisions(db, item.workspace_id, item.id),
        authors=authors,
        editors=editors,
        metadata=metadata_from_item(item, authors, editors, identifiers),
    )


async def _open_files(db: AsyncSession, context: WorkspaceContext, item: Item) -> ItemFilesData:
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
    return ItemFilesData(
        item=item,
        revisions=await _revisions(db, item.workspace_id, item.id, all_revisions=True),
        attachments=attachments,
    )


async def _open_organize(
    db: AsyncSession, context: WorkspaceContext, item: Item
) -> ItemOrganizationData:
    tags = await _assigned_tags(db, item)
    member_project_ids = select(ProjectMember.project_id).where(
        ProjectMember.workspace_id == context.workspace_id,
        ProjectMember.user_id == context.actor_id,
    )
    is_participating = (Project.participation == ProjectParticipation.workspace) | Project.id.in_(
        member_project_ids
    )
    project_rows = (
        await db.execute(
            select(Project, is_participating)
            .where(
                Project.workspace_id == item.workspace_id,
                Project.state == ProjectState.active,
                Project.id.in_(visible_project_ids_query(context)),
            )
            .order_by(Project.name)
        )
    ).all()
    project_options = tuple(
        ProjectAssignmentOption(project=project, is_participating=bool(member))
        for project, member in project_rows
    )
    visible_project_ids = {option.project.id for option in project_options}
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
    return ItemOrganizationData(
        item=item,
        revisions=await _revisions(db, item.workspace_id, item.id),
        tags=tags,
        projects=project_options,
        assigned_project_ids=assigned_project_ids,
        tag_matrix=await get_tag_matrix_for_item(db, item),
    )


async def _open_annotations(
    db: AsyncSession, context: WorkspaceContext, item: Item
) -> ItemAnnotationsData:
    moderator = action_allowed(context, ResourceAction.project_annotation_review)
    revisions = await _revisions(db, item.workspace_id, item.id, all_revisions=True)
    annotations: tuple[AnnotationView, ...] = ()
    if revisions:
        visible_project_items = (
            select(ProjectItem.id)
            .join(Project, Project.id == ProjectItem.project_id)
            .where(
                ProjectItem.workspace_id == item.workspace_id,
                Project.state != ProjectState.deleted,
                Project.id.in_(visible_project_ids_query(context)),
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
                    visible_annotation_scope_predicate(
                        context,
                        project_item_ids=visible_project_items,
                    ),
                )
                .order_by(PdfAnnotation.updated_at.desc())
            )
        ).all()
        annotations = tuple(
            AnnotationView(annotation=row[0], revision=row[1], author=row[2]) for row in rows
        )
    return ItemAnnotationsData(
        item=item,
        revisions=revisions,
        annotations=annotations,
    )


async def _open_discussion(
    db: AsyncSession, context: WorkspaceContext, item: Item
) -> ItemDiscussionData:
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
    return ItemDiscussionData(
        item=item,
        revisions=await _revisions(db, item.workspace_id, item.id),
        messages=messages,
    )


async def open_item_section(
    db: AsyncSession,
    context: WorkspaceContext,
    item_id: str,
    section: ItemSection,
) -> ItemSectionResult:
    try:
        require_action(context, ResourceAction.workspace_read)
        item = await get_item(db, context, item_id)
        if item is None:
            raise ResourceUnavailable("Item not found")
        view: ItemSectionResult
        match section:
            case ItemSection.overview:
                view = await _open_overview(db, context, item)
            case ItemSection.metadata:
                view = await _open_metadata(db, context, item)
            case ItemSection.files:
                view = await _open_files(db, context, item)
            case ItemSection.organize:
                view = await _open_organize(db, context, item)
            case ItemSection.annotations:
                view = await _open_annotations(db, context, item)
            case ItemSection.discussion:
                view = await _open_discussion(db, context, item)
        await _record_read(db, context.actor, context.workspace_id, item.id)
        await db.commit()
        return view
    except Exception:
        await db.rollback()
        raise
