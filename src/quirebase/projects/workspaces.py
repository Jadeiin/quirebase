from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from advanced_alchemy.filters import LimitOffset, SearchFilter
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from quirebase.access import (
    ResourceAction,
    WorkspaceContext,
    discoverable_project_ids_query,
    lock_workspace_context,
    require_action,
    require_workspace_action,
    workspace_select,
)
from quirebase.audit import record_event
from quirebase.core.errors import ProjectLifecycleError, ResourceUnavailable, ValidationFailure
from quirebase.documents import delete_project_item_annotations
from quirebase.models import (
    Item,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectParticipation,
    ProjectState,
    User,
    WorkspaceMember,
    WorkspaceMemberState,
)

from ._locking import lock_project_root
from ._persistence import ProjectMemberRepository, ProjectService
from .lifecycle import _validate_description, _validate_name
from .loaders import require_project
from .members import ProjectParticipant

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from advanced_alchemy.filters import StatementFilter
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ProjectWorkspace:
    project: Project
    active_participants: tuple[ProjectParticipant, ...]
    items: tuple[Item, ...]
    is_participating: bool


async def create_project(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    name: str,
    participation: ProjectParticipation | str = ProjectParticipation.workspace,
    description: str = "",
) -> Project:
    normalized = _validate_name(name)
    try:
        parsed_participation = ProjectParticipation(participation)
    except ValueError as error:
        raise ValidationFailure("invalid Project participation") from error
    normalized_description = _validate_description(description)
    create_action = ResourceAction.project_create
    context = await require_workspace_action(
        db,
        user,
        workspace_id,
        create_action,
        relation=parsed_participation.value,
    )
    project = Project(
        workspace_id=workspace_id,
        name=normalized,
        created_by=user.id,
        participation=parsed_participation,
        description=normalized_description,
    )
    project = await ProjectService(db).create(project)
    if parsed_participation is ProjectParticipation.open:
        await ProjectMemberRepository(session=db).add(
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
        authorization_resource_action=create_action.value,
    )
    await db.commit()
    return project


async def list_workspace_projects(
    db: AsyncSession,
    context: WorkspaceContext,
    *,
    view: Literal["mine", "joinable", "all"] = "all",
    limit: int | None = 25,
    offset: int = 0,
    search: str = "",
) -> tuple[list[tuple[Project, int, bool]], int]:
    """List discoverable Projects, optionally limited to the caller's participation view."""
    if view not in {"mine", "joinable", "all"}:
        raise ValidationFailure("invalid Project list view")
    require_action(context, ResourceAction.workspace_read)
    member_ids = (
        workspace_select(ProjectMember, context)
        .join(Project, Project.id == ProjectMember.project_id)
        .where(ProjectMember.user_id == context.actor_id)
        .with_only_columns(ProjectMember.project_id)
    )
    is_participating = (Project.participation == ProjectParticipation.workspace) | Project.id.in_(
        member_ids
    )
    query = (
        workspace_select(Project, context)
        .where(
            Project.state != ProjectState.deleted,
            Project.id.in_(discoverable_project_ids_query(context)),
        )
        .order_by(Project.name, Project.id)
    )
    if view == "mine":
        query = query.where(is_participating)
    elif view == "joinable":
        query = query.where(
            Project.state == ProjectState.active,
            Project.participation == ProjectParticipation.open,
            ~is_participating,
        )
    filters: list[StatementFilter] = (
        [LimitOffset(limit=limit, offset=offset)] if limit is not None else []
    )
    if search.strip():
        filters.append(SearchFilter(field_name="name", value=search.strip(), ignore_case=True))
    roots, total = await ProjectService(session=db, statement=query).get_many_and_count(
        *filters,
    )
    ids = [project.id for project in roots]
    if not ids:
        return [], total
    counts: dict[UUID, int] = dict(
        (
            await db.execute(
                workspace_select(ProjectItem, context)
                .with_only_columns(ProjectItem.project_id, func.count(ProjectItem.id))
                .where(ProjectItem.project_id.in_(ids))
                .group_by(ProjectItem.project_id)
            )
        )
        .tuples()
        .all()
    )
    joined = set((await db.scalars(member_ids.where(ProjectMember.project_id.in_(ids)))).all())
    return [
        (
            project,
            counts.get(project.id, 0),
            project.participation is ProjectParticipation.workspace or project.id in joined,
        )
        for project in roots
    ], total


async def open_project_workspace(
    db: AsyncSession, workspace: WorkspaceContext, project_id: UUID
) -> ProjectWorkspace:
    context = await require_project(db, workspace, project_id)
    workspace_id = workspace.workspace_id
    participant_users: Sequence[User] = ()
    is_participating = context.project.participation is ProjectParticipation.workspace
    if context.project.participation is not ProjectParticipation.workspace:
        participant_users = (
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
        is_participating = (
            await db.scalar(
                select(ProjectMember.id).where(
                    ProjectMember.workspace_id == workspace_id,
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == workspace.actor_id,
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
        active_participants=tuple(
            ProjectParticipant(user_id=row.id, username=row.username) for row in participant_users
        ),
        items=items,
        is_participating=is_participating,
    )


async def add_item_to_project(
    db: AsyncSession, user: User, workspace_id: UUID, project_id: UUID, item_id: UUID
) -> None:
    workspace = await lock_workspace_context(db, user, workspace_id)
    project = await lock_project_root(db, workspace, project_id, lock="shared")
    require_action(workspace, ResourceAction.project_item_manage)
    if project.state is not ProjectState.active:
        raise ProjectLifecycleError("Project is read-only")
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
            authorization_role=workspace.role.value,
            authorization_resource_action=ResourceAction.project_item_manage.value,
        )
    await db.commit()


async def remove_item_from_project(
    db: AsyncSession, user: User, workspace_id: UUID, project_id: UUID, item_id: UUID
) -> None:
    workspace = await lock_workspace_context(db, user, workspace_id)
    project = await lock_project_root(db, workspace, project_id, lock="shared")
    require_action(workspace, ResourceAction.project_item_manage)
    if project.state is not ProjectState.active:
        raise ProjectLifecycleError("Project is read-only")
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
            authorization_role=workspace.role.value,
            authorization_resource_action=ResourceAction.project_item_manage.value,
        )
    await db.commit()


async def add_items_to_project(
    db: AsyncSession, user: User, workspace_id: UUID, project_id: UUID, item_ids: list[UUID]
) -> int:
    workspace = await lock_workspace_context(db, user, workspace_id)
    project = await lock_project_root(db, workspace, project_id, lock="shared")
    require_action(workspace, ResourceAction.project_item_manage)
    if project.state is not ProjectState.active:
        raise ProjectLifecycleError("Project is read-only")
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
