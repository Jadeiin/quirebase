from __future__ import annotations

from typing import TYPE_CHECKING

from advanced_alchemy.filters import LimitOffset, OrderBy, SearchFilter
from sqlalchemy import func, select

from quirebase.access import (
    ResourceAction,
    WorkspaceContext,
    require_action,
    require_workspace_action,
)
from quirebase.models import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)

from ._persistence import WorkspaceMemberRepository, WorkspaceService

if TYPE_CHECKING:
    from uuid import UUID

    from advanced_alchemy.filters import StatementFilter
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession


async def list_workspaces(
    db: AsyncSession,
    actor: User,
    *,
    limit: int | None = 25,
    offset: int = 0,
    search: str = "",
) -> tuple[list[tuple[Workspace, WorkspaceMember]], int]:
    if not actor.active:
        return [], 0
    query = (
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == actor.id,
            WorkspaceMember.state == WorkspaceMemberState.active,
            WorkspaceMember.terminated_at.is_(None),
            Workspace.state != WorkspaceState.deleted,
        )
        .order_by(Workspace.name, Workspace.id)
    )
    filters: list[StatementFilter] = (
        [LimitOffset(limit=limit, offset=offset)] if limit is not None else []
    )
    if search.strip():
        filters.append(SearchFilter(field_name="name", value=search.strip(), ignore_case=True))
    roots, total = await WorkspaceService(session=db, statement=query).get_many_and_count(
        *filters,
    )
    if not roots:
        return [], total
    members = {
        member.workspace_id: member
        for member in await WorkspaceMemberRepository(session=db).get_many(
            WorkspaceMember.workspace_id.in_([workspace.id for workspace in roots]),
            user_id=actor.id,
            state=WorkspaceMemberState.active,
            terminated_at=None,
        )
    }
    return [
        (workspace, members[workspace.id]) for workspace in roots if workspace.id in members
    ], total


def _workspace_owners_query():
    current_owner = (
        WorkspaceMember.workspace_id == Workspace.id,
        WorkspaceMember.role == WorkspaceRole.owner,
        WorkspaceMember.terminated_at.is_(None),
    )
    owner_count = (
        select(func.count(WorkspaceMember.id))
        .where(*current_owner)
        .correlate(Workspace)
        .scalar_subquery()
    )
    owner_id = (
        select(User.id)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(
            *current_owner,
            WorkspaceMember.state == WorkspaceMemberState.active,
            User.active.is_(True),
            owner_count == 1,
        )
        .correlate(Workspace)
        .scalar_subquery()
    )
    return select(Workspace.id, owner_id.label("owner_id")).where(
        Workspace.state != WorkspaceState.deleted
    )


async def workspace_owner_ids(db: AsyncSession, workspace_ids: set[UUID]) -> dict[UUID, UUID]:
    """Return owners of surviving Workspaces, validating membership and account state."""
    if not workspace_ids:
        return {}
    rows = await db.execute(_workspace_owners_query().where(Workspace.id.in_(workspace_ids)))
    # Read root existence and membership in one snapshot: a concurrent root
    # deletion also removes its owner and is not an invariant violation.
    owner_rows = rows.tuples().all()
    missing = {workspace_id for workspace_id, owner_id in owner_rows if owner_id is None}
    if missing:
        raise RuntimeError(f"Workspace owner invariant failed for: {sorted(missing)}")
    return {workspace_id: owner_id for workspace_id, owner_id in owner_rows if owner_id is not None}


async def check_workspace_integrity(db: AsyncSession) -> list[str]:
    rows = await db.execute(_workspace_owners_query().order_by(Workspace.id))
    return [
        f"Workspace {workspace_id} must have exactly one current active owner with an active account"
        for workspace_id, owner_id in rows
        if owner_id is None
    ]


async def get_workspace(
    db: AsyncSession, actor: User, workspace_id: UUID
) -> tuple[Workspace, WorkspaceMember]:
    context = await require_workspace_action(db, actor, workspace_id, ResourceAction.workspace_read)
    return context.workspace, context.membership


async def list_workspace_members(
    db: AsyncSession,
    context: WorkspaceContext,
    *,
    limit: int = 25,
    offset: int = 0,
    search: str = "",
) -> tuple[list[WorkspaceMember], int]:
    require_action(context, ResourceAction.workspace_read)
    query = (
        select(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(
            WorkspaceMember.workspace_id == context.workspace_id,
            WorkspaceMember.state == WorkspaceMemberState.active,
            WorkspaceMember.terminated_at.is_(None),
            User.active.is_(True),
        )
    )
    return await _member_page(db, query, limit, offset, search)


async def list_workspace_governance_members(
    db: AsyncSession,
    context: WorkspaceContext,
    *,
    limit: int = 25,
    offset: int = 0,
    search: str = "",
) -> tuple[list[WorkspaceMember], int]:
    require_action(context, ResourceAction.workspace_member_read)
    query = (
        select(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(
            WorkspaceMember.workspace_id == context.workspace_id,
            WorkspaceMember.terminated_at.is_(None),
        )
    )
    return await _member_page(db, query, limit, offset, search)


async def _member_page(
    db: AsyncSession, query: Select[tuple[WorkspaceMember]], limit: int, offset: int, search: str
) -> tuple[list[WorkspaceMember], int]:
    if search.strip():
        matching_users = SearchFilter(field_name="username", value=search.strip(), ignore_case=True)
        query = query.where(
            WorkspaceMember.user_id.in_(matching_users.append_to_statement(select(User.id), User))
        )
    records, total = await WorkspaceMemberRepository(
        session=db, statement=query
    ).get_many_and_count(
        LimitOffset(limit=limit, offset=offset),
        OrderBy(field_name=User.username),
        OrderBy(field_name="id"),
    )
    return list(records), total
