from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from quirebase.access import (
    Capability,
    require_project_context,
    require_workspace_capability,
    visible_project_ids_query,
    workspace_select,
)
from quirebase.audit import record_event
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.documents import delete_project_item_annotations
from quirebase.models import (
    Item,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectState,
    ProjectVisibility,
    User,
    WorkspaceMember,
    WorkspaceMemberState,
)

from ._locking import guard_project, lock_project_participation_workspace

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ProjectWorkspaceMember:
    user: User


@dataclass(frozen=True)
class ProjectWorkspace:
    project: Project
    members: tuple[ProjectWorkspaceMember, ...]
    items: tuple[Item, ...]
    is_member: bool


async def create_project(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    name: str,
    visibility: ProjectVisibility | str = ProjectVisibility.workspace,
    description: str = "",
) -> Project:
    normalized = name.strip()
    if not normalized or len(normalized) > 240:
        raise ValidationFailure("Project name must contain 1 to 240 characters")
    try:
        parsed_visibility = ProjectVisibility(visibility)
    except ValueError as error:
        raise ValidationFailure("invalid Project visibility") from error
    normalized_description = description.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized_description) > 2000:
        raise ValidationFailure("Project description is too long")
    if parsed_visibility is ProjectVisibility.open:
        await lock_project_participation_workspace(db, workspace_id)
    create_capability = (
        Capability.projects_create_managed
        if parsed_visibility is ProjectVisibility.managed
        else Capability.projects_create
    )
    context = await require_workspace_capability(db, user, workspace_id, create_capability)
    project = Project(
        workspace_id=workspace_id,
        name=normalized,
        created_by=user.id,
        visibility=parsed_visibility,
        description=normalized_description,
    )
    db.add(project)
    await db.flush()
    if parsed_visibility is ProjectVisibility.open:
        db.add(
            ProjectMember(
                workspace_id=workspace_id,
                project_id=project.id,
                user_id=user.id,
            )
        )
    record_event(
        db,
        user.id,
        "project.create",
        "project",
        project.id,
        workspace_id=workspace_id,
        project_id=project.id,
        authorization_role=context.role.value,
        authorization_capability=create_capability.value,
    )
    await db.commit()
    return project


async def list_workspace_projects(
    db: AsyncSession, user: User, workspace_id: str
) -> list[tuple[Project, int, bool]]:
    context = await require_workspace_capability(db, user, workspace_id, Capability.workspace_read)
    member_ids = (
        workspace_select(ProjectMember, context)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(ProjectMember.user_id == user.id)
        .with_only_columns(ProjectMember.project_id)
    )
    rows = (
        await db.execute(
            workspace_select(Project, context)
            .with_only_columns(
                Project,
                func.count(ProjectItem.id),
                (Project.visibility == ProjectVisibility.workspace) | Project.id.in_(member_ids),
            )
            .outerjoin(
                ProjectItem,
                ProjectItem.project_id == Project.id,
            )
            .where(
                Project.state != ProjectState.deleted,
                Project.id.in_(visible_project_ids_query(context)),
            )
            .group_by(Project.id)
            .order_by(Project.name)
        )
    ).all()
    return [(row[0], row[1], bool(row[2])) for row in rows]


async def list_joinable_projects(
    db: AsyncSession, user: User, workspace_id: str
) -> list[tuple[Project, int]]:
    """List active open Projects the current Workspace member has not joined."""
    context = await require_workspace_capability(db, user, workspace_id, Capability.workspace_read)
    member_ids = (
        workspace_select(ProjectMember, context)
        .where(ProjectMember.user_id == user.id)
        .with_only_columns(ProjectMember.project_id)
    )
    rows = await db.execute(
        workspace_select(Project, context)
        .with_only_columns(Project, func.count(ProjectItem.id))
        .outerjoin(ProjectItem, ProjectItem.project_id == Project.id)
        .where(
            Project.state == ProjectState.active,
            Project.visibility == ProjectVisibility.open,
            ~Project.id.in_(member_ids),
        )
        .group_by(Project.id)
        .order_by(Project.name)
    )
    return [(row[0], row[1]) for row in rows.all()]


async def open_project_workspace(
    db: AsyncSession, user: User, workspace_id: str, project_id: str
) -> ProjectWorkspace:
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.workspace_read
    )
    members_rows: Sequence[User] = ()
    is_member = context.project.visibility is ProjectVisibility.workspace
    if context.project.visibility is not ProjectVisibility.workspace:
        members_rows = (
            await db.scalars(
                select(User)
                .join(ProjectMember, ProjectMember.user_id == User.id)
                .join(
                    WorkspaceMember,
                    (WorkspaceMember.workspace_id == ProjectMember.workspace_id)
                    & (WorkspaceMember.user_id == User.id),
                )
                .where(
                    ProjectMember.workspace_id == workspace_id,
                    ProjectMember.project_id == project_id,
                    User.active.is_(True),
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == User.id,
                    WorkspaceMember.state == WorkspaceMemberState.active,
                    WorkspaceMember.terminated_at.is_(None),
                )
                .order_by(User.username)
            )
        ).all()
        is_member = (
            await db.scalar(
                select(ProjectMember.id).where(
                    ProjectMember.workspace_id == workspace_id,
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == user.id,
                )
            )
            is not None
        )
    items = tuple(
        (
            await db.scalars(
                workspace_select(Item, context.workspace)
                .join(ProjectItem, ProjectItem.item_id == Item.id)
                .where(
                    ProjectItem.project_id == project_id,
                )
                .order_by(Item.updated_at.desc())
            )
        ).all()
    )
    return ProjectWorkspace(
        project=context.project,
        members=tuple(ProjectWorkspaceMember(user=row) for row in members_rows),
        items=items,
        is_member=is_member,
    )


async def add_item_to_project(
    db: AsyncSession, user: User, workspace_id: str, project_id: str, item_id: str
) -> None:
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.projects_manage
    )
    await guard_project(db, project_id, state=ProjectState.active)
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.projects_manage
    )
    item = await db.scalar(
        select(Item).where(Item.id == item_id, Item.workspace_id == workspace_id)
    )
    if item is None:
        raise ResourceUnavailable("Item or Project not found")
    dialect = db.get_bind().dialect.name
    insert = pg_insert(ProjectItem) if dialect == "postgresql" else sqlite_insert(ProjectItem)
    try:
        async with db.begin_nested():
            result = await db.execute(
                insert.values(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    item_id=item_id,
                    added_by=user.id,
                ).on_conflict_do_nothing(index_elements=["workspace_id", "project_id", "item_id"])
            )
    except IntegrityError as error:
        raise ResourceUnavailable("Item or Project not found") from error
    if getattr(result, "rowcount", 0):
        record_event(
            db,
            user.id,
            "project.item.add",
            "item",
            item_id,
            detail={"project_id": project_id},
            workspace_id=workspace_id,
            project_id=project_id,
            authorization_role=context.workspace.role.value,
            authorization_capability=Capability.projects_manage.value,
        )
    await db.commit()


async def remove_item_from_project(
    db: AsyncSession, user: User, workspace_id: str, project_id: str, item_id: str
) -> None:
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.projects_manage
    )
    await guard_project(db, project_id, state=ProjectState.active)
    context = await require_project_context(
        db, user, workspace_id, project_id, Capability.projects_manage
    )
    project_item = await db.scalar(
        select(ProjectItem)
        .where(
            ProjectItem.workspace_id == workspace_id,
            ProjectItem.project_id == project_id,
            ProjectItem.item_id == item_id,
        )
        .with_for_update()
    )
    if project_item is not None:
        await delete_project_item_annotations(db, workspace_id, project_item.id)
        await db.execute(delete(ProjectItem).where(ProjectItem.id == project_item.id))
        record_event(
            db,
            user.id,
            "project.item.remove",
            "item",
            item_id,
            detail={"project_id": project_id},
            workspace_id=workspace_id,
            project_id=project_id,
            authorization_role=context.workspace.role.value,
            authorization_capability=Capability.projects_manage.value,
        )
    await db.commit()


async def add_items_to_project(
    db: AsyncSession, user: User, workspace_id: str, project_id: str, item_ids: list[str]
) -> int:
    await require_project_context(db, user, workspace_id, project_id, Capability.projects_manage)
    await guard_project(db, project_id, state=ProjectState.active)
    await require_project_context(db, user, workspace_id, project_id, Capability.projects_manage)
    ids = tuple(sorted(dict.fromkeys(item_ids)))
    if not ids:
        return 0
    accessible = set(
        (
            await db.scalars(
                select(Item.id).where(Item.workspace_id == workspace_id, Item.id.in_(ids))
            )
        ).all()
    )
    if accessible != set(ids):
        raise ResourceUnavailable("Item or Project not found")
    rows = [
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "item_id": item_id,
            "added_by": user.id,
        }
        for item_id in ids
    ]
    dialect = db.get_bind().dialect.name
    insert = pg_insert(ProjectItem) if dialect == "postgresql" else sqlite_insert(ProjectItem)
    try:
        async with db.begin_nested():
            result = await db.execute(
                insert.values(rows).on_conflict_do_nothing(
                    index_elements=["workspace_id", "project_id", "item_id"]
                )
            )
    except IntegrityError as error:
        raise ResourceUnavailable("Item or Project not found") from error
    return int(getattr(result, "rowcount", 0) or 0)
