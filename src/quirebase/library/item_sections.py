"""Open one Item section and build its section-specific read model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import case, func, select
from sqlalchemy.orm import selectinload

from quirebase.access import (
    ResourceAction,
    WorkspaceContext,
    get_item,
    require_action,
)
from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
from quirebase.core.persistence import conflict_insert
from quirebase.documents import (
    AnnotationView,
    DocumentInfo,
    count_item_annotations,
    count_item_attachments,
    list_item_annotation_views,
    list_item_attachments,
    list_item_revisions,
)
from quirebase.library._metadata import ItemMetadata, metadata_from_item
from quirebase.library.authors import get_item_authors
from quirebase.library.tags import TagMatrix, get_tag_matrix_for_item
from quirebase.models import (
    DiscussionMessage,
    Item,
    ItemIdentifier,
    ItemRead,
    ItemTag,
    Project,
    ProjectItem,
    Tag,
    User,
)
from quirebase.projects import list_item_organize_projects

if TYPE_CHECKING:
    from uuid import UUID

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
    revisions: tuple[DocumentInfo, ...]


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
    metadata: ItemMetadata


@dataclass(frozen=True)
class ItemFilesData(ItemSectionData):
    attachments: tuple[DocumentInfo, ...]


@dataclass(frozen=True)
class ProjectAssignmentOption:
    project: Project
    is_participating: bool


@dataclass(frozen=True)
class ItemOrganizationData(ItemSectionData):
    tags: tuple[Tag, ...]
    projects: tuple[ProjectAssignmentOption, ...]
    assigned_project_ids: frozenset[UUID]
    tag_matrix: TagMatrix


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
    revisions = await list_item_revisions(db, item.workspace_id, item.id, all_revisions=True)
    annotation_count = await count_item_annotations(db, context, item.id)
    message_count = (
        await db.scalar(
            select(func.count(DiscussionMessage.id)).where(
                DiscussionMessage.workspace_id == item.workspace_id,
                DiscussionMessage.item_id == item.id,
            )
        )
        or 0
    )
    attachment_count = await count_item_attachments(db, item.workspace_id, item.id)
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
        revisions=await list_item_revisions(db, item.workspace_id, item.id),
        metadata=metadata_from_item(item, authors, editors, identifiers),
    )


async def _open_files(db: AsyncSession, context: WorkspaceContext, item: Item) -> ItemFilesData:
    attachments = await list_item_attachments(db, item.workspace_id, item.id)
    return ItemFilesData(
        item=item,
        revisions=await list_item_revisions(db, item.workspace_id, item.id, all_revisions=True),
        attachments=attachments,
    )


async def _open_organize(
    db: AsyncSession, context: WorkspaceContext, item: Item
) -> ItemOrganizationData:
    tags = await _assigned_tags(db, item)
    project_options = tuple(
        ProjectAssignmentOption(project, participating)
        for project, participating in await list_item_organize_projects(db, context)
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
        revisions=await list_item_revisions(db, item.workspace_id, item.id),
        tags=tags,
        projects=project_options,
        assigned_project_ids=assigned_project_ids,
        tag_matrix=await get_tag_matrix_for_item(db, item),
    )


async def _open_annotations(
    db: AsyncSession, context: WorkspaceContext, item: Item
) -> ItemAnnotationsData:
    revisions = await list_item_revisions(db, item.workspace_id, item.id, all_revisions=True)
    annotations = await list_item_annotation_views(db, context, item.id)
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
        revisions=await list_item_revisions(db, item.workspace_id, item.id),
        messages=messages,
    )


async def open_item_section(
    db: AsyncSession,
    context: WorkspaceContext,
    item_id: UUID,
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
        read_at = datetime.now(UTC)
        statement = conflict_insert(db, ItemRead).values(
            workspace_id=context.workspace_id,
            user_id=context.actor.id,
            item_id=item.id,
            last_read_at=read_at,
        )
        async with db.begin_nested():
            await db.execute(
                statement.on_conflict_do_update(
                    index_elements=[ItemRead.user_id, ItemRead.item_id],
                    set_={
                        # Validate the supplied lineage on the update path too.
                        "workspace_id": statement.excluded.workspace_id,
                        "last_read_at": case(
                            (ItemRead.last_read_at < read_at, read_at), else_=ItemRead.last_read_at
                        ),
                    },
                )
            )
        await db.commit()
        return view
    except Exception:
        await db.rollback()
        raise
