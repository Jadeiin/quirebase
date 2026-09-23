from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from quirebase.access.items import can_read_item
from quirebase.access.projects import require_project_member
from quirebase.audit import record_event
from quirebase.core.errors import (
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
)
from quirebase.models import (
    Attachment,
    FileRevision,
    Item,
    ItemAttachment,
    ItemFileRevision,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectRole,
    ProjectSharingMode,
    ProjectState,
    ProjectVisibility,
    User,
)

from ._locking import guard_project
from .sharing import clone_item_for_project

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ProjectWorkspaceMember:
    user: User
    role: ProjectRole


@dataclass(frozen=True)
class ProjectWorkspace:
    project: Project
    membership: ProjectMember
    members: tuple[ProjectWorkspaceMember, ...]
    items: tuple[Item, ...]


async def create_project(
    db: AsyncSession,
    user: User,
    name: str,
    visibility: ProjectVisibility | str = ProjectVisibility.private,
    description: str = "",
    sharing_mode: ProjectSharingMode | str = ProjectSharingMode.live,
) -> Project:
    creator = await db.scalar(
        select(User).where(User.id == user.id, User.active.is_(True)).with_for_update(read=True)
    )
    if creator is None:
        raise ResourceUnavailable("active user required")
    normalized = name.strip()
    if not normalized:
        raise ValidationFailure("project name is required")
    if len(normalized) > 240:
        raise ValidationFailure("project name is too long")
    try:
        parsed_visibility = ProjectVisibility(visibility)
    except ValueError as error:
        raise ValidationFailure("invalid project visibility") from error
    try:
        parsed_mode = ProjectSharingMode(sharing_mode)
    except ValueError as error:
        raise ValidationFailure("invalid project sharing mode") from error
    normalized_description = description.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized_description) > 2000:
        raise ValidationFailure("project description is too long")
    project = Project(
        name=normalized,
        created_by=creator.id,
        visibility=parsed_visibility,
        description=normalized_description,
        sharing_mode=parsed_mode,
    )
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=creator.id, role=ProjectRole.admin))
    record_event(db, creator.id, "project.create", "project", project.id)
    await db.commit()
    return project


async def list_user_projects(db: AsyncSession, user: User) -> list[tuple[Project, str, int]]:
    rows = (
        await db.execute(
            select(Project, ProjectMember.role, func.count(ProjectItem.item_id))
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .outerjoin(ProjectItem, ProjectItem.project_id == Project.id)
            .where(ProjectMember.user_id == user.id)
            .group_by(Project.id, ProjectMember.role)
            .order_by(Project.name)
        )
    ).all()
    return [(row[0], row[1], row[2]) for row in rows]


async def list_joinable_projects(db: AsyncSession, user: User) -> list[tuple[Project, int]]:
    rows = await db.execute(
        select(Project, func.count(ProjectItem.item_id))
        .outerjoin(ProjectItem)
        .where(
            Project.visibility == ProjectVisibility.public,
            Project.state == "active",
            ~select(ProjectMember.project_id)
            .where(ProjectMember.project_id == Project.id, ProjectMember.user_id == user.id)
            .exists(),
        )
        .group_by(Project.id)
        .order_by(Project.name)
    )
    return [(row[0], row[1]) for row in rows]


async def join_project(db: AsyncSession, user: User, project_id: str) -> ProjectMember:
    await guard_project(
        db,
        project_id,
        state=ProjectState.active,
        visibility=ProjectVisibility.public,
        message="public project not available",
    )
    existing = await db.get(ProjectMember, (project_id, user.id), populate_existing=True)
    if existing:
        await db.commit()
        return existing
    member = ProjectMember(project_id=project_id, user_id=user.id, role=ProjectRole.viewer)
    db.add(member)
    record_event(db, user.id, "project.member.join", "project", project_id)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent retry may have inserted the same composite key.  The
        # failed transaction must be rolled back before reloading it.
        await db.rollback()
        existing = await db.get(ProjectMember, (project_id, user.id))
        if existing is None:
            raise
        return existing
    return member


async def open_project_workspace(db: AsyncSession, user: User, project_id: str) -> ProjectWorkspace:
    membership = await require_project_member(db, user, project_id)
    project = await db.get(Project, project_id)
    if project is None:
        raise ResourceNotFound("project not found")
    members_rows = (
        await db.execute(
            select(User, ProjectMember.role)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project_id)
            .order_by(User.username)
        )
    ).all()
    members = tuple(ProjectWorkspaceMember(user=row[0], role=row[1]) for row in members_rows)
    items = tuple(
        (
            await db.scalars(
                select(Item)
                .join(ProjectItem, ProjectItem.item_id == Item.id)
                .where(ProjectItem.project_id == project_id)
                .order_by(Item.updated_at.desc())
            )
        ).all()
    )
    return ProjectWorkspace(
        project=project,
        membership=membership,
        members=members,
        items=items,
    )


async def add_item_to_project(db: AsyncSession, user: User, project_id: str, item_id: str) -> None:
    project = await guard_project(
        db,
        project_id,
        state=ProjectState.active,
        message="item or project not accessible or insufficient permissions",
    )
    item = await db.get(Item, item_id, populate_existing=True)
    if item is None or not await can_read_item(db, user, item_id):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    membership = await db.get(ProjectMember, (project_id, user.id), populate_existing=True)
    if membership is None or membership.role not in (ProjectRole.admin, ProjectRole.editor):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    if project.sharing_mode is ProjectSharingMode.live and item.owner_id == user.id:
        target_item = item
    else:
        target_item = await clone_item_for_project(db, item, user)
    target_item_id = target_item.id
    created = False
    if (
        await db.scalar(
            select(ProjectItem).where(
                ProjectItem.project_id == project_id, ProjectItem.item_id == target_item_id
            )
        )
        is None
    ):
        try:
            async with db.begin_nested():
                db.add(ProjectItem(project_id=project_id, item_id=target_item_id, added_by=user.id))
                await db.flush()
                created = True
        except IntegrityError as error:
            if (
                await db.scalar(
                    select(ProjectItem).where(
                        ProjectItem.project_id == project_id, ProjectItem.item_id == target_item_id
                    )
                )
                is None
            ):
                raise ResourceUnavailable(
                    "item or project not accessible or insufficient permissions"
                ) from error
    if created:
        record_event(
            db,
            user.id,
            "project.item.add",
            "item",
            target_item_id,
            detail={
                "project_id": project_id,
                "source_item_id": item_id,
                "copy": target_item_id != item_id,
            },
        )
    await db.commit()


async def remove_item_from_project(
    db: AsyncSession, user: User, project_id: str, item_id: str
) -> None:
    await guard_project(
        db,
        project_id,
        state=ProjectState.active,
        message="item or project not accessible or insufficient permissions",
    )
    item = await db.get(Item, item_id, populate_existing=True)
    if item is None or not await can_read_item(db, user, item_id):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    membership = await db.get(ProjectMember, (project_id, user.id), populate_existing=True)
    if membership is None or membership.role not in (ProjectRole.admin, ProjectRole.editor):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    result = await db.execute(
        delete(ProjectItem).where(
            ProjectItem.project_id == project_id, ProjectItem.item_id == item_id
        )
    )
    if getattr(result, "rowcount", 0):
        if (
            item.owner_id is None
            and await db.scalar(
                select(ProjectItem.id).where(ProjectItem.item_id == item.id).limit(1)
            )
            is None
        ):
            revision_ids = list(
                (
                    await db.scalars(
                        select(ItemFileRevision.file_revision_id).where(
                            ItemFileRevision.item_id == item.id
                        )
                    )
                ).all()
            )
            attachment_ids = list(
                (
                    await db.scalars(
                        select(ItemAttachment.attachment_id).where(
                            ItemAttachment.item_id == item.id
                        )
                    )
                ).all()
            )
            await db.execute(delete(ItemFileRevision).where(ItemFileRevision.item_id == item.id))
            await db.execute(delete(ItemAttachment).where(ItemAttachment.item_id == item.id))
            if revision_ids:
                await db.execute(
                    delete(FileRevision).where(
                        FileRevision.id.in_(revision_ids),
                        ~exists().where(ItemFileRevision.file_revision_id == FileRevision.id),
                    )
                )
            if attachment_ids:
                await db.execute(
                    delete(Attachment).where(
                        Attachment.id.in_(attachment_ids),
                        ~exists().where(ItemAttachment.attachment_id == Attachment.id),
                    )
                )
            await db.delete(item)
        record_event(
            db,
            user.id,
            "project.item.remove",
            "item",
            item_id,
            detail={"project_id": project_id},
        )
    await db.commit()


async def add_items_to_project(
    db: AsyncSession, user: User, project_id: str, item_ids: list[str]
) -> int:
    """Add many Item associations under the Projects module's root guard."""
    project = await guard_project(
        db,
        project_id,
        state=ProjectState.active,
        message="item or project not accessible or insufficient permissions",
    )
    membership = await db.get(ProjectMember, (project_id, user.id), populate_existing=True)
    if membership is None or membership.role not in (ProjectRole.admin, ProjectRole.editor):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    ids = tuple(sorted(dict.fromkeys(item_ids)))
    if not ids:
        return 0
    accessible = [item_id for item_id in ids if await can_read_item(db, user, item_id)]
    if len(accessible) != len(ids):
        raise ResourceUnavailable("item or project not accessible or insufficient permissions")
    target_ids: list[str] = []
    for item_id in accessible:
        item = await db.get(Item, item_id, populate_existing=True)
        if item is None:
            raise ResourceUnavailable("item or project not accessible or insufficient permissions")
        if project.sharing_mode is ProjectSharingMode.live and item.owner_id == user.id:
            target_ids.append(item.id)
        else:
            target_ids.append((await clone_item_for_project(db, item, user)).id)
    rows = [
        {"project_id": project_id, "item_id": item_id, "added_by": user.id}
        for item_id in target_ids
    ]
    dialect = db.get_bind().dialect.name
    insert = pg_insert(ProjectItem) if dialect == "postgresql" else sqlite_insert(ProjectItem)
    try:
        async with db.begin_nested():
            result = await db.execute(
                insert.values(rows).on_conflict_do_nothing(index_elements=["project_id", "item_id"])
            )
    except IntegrityError as error:
        # An Item may disappear after the accessibility check but before the
        # association insert.  Treat the FK race as a normal rejected
        # assignment rather than leaking a failed transaction to the caller.
        raise ResourceUnavailable(
            "item or project not accessible or insufficient permissions"
        ) from error
    count = int(getattr(result, "rowcount", 0) or 0)
    await db.commit()
    return count
