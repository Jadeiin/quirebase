from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from advanced_alchemy.filters import LimitOffset, OrderBy, SearchFilter
from sqlalchemy import func, select

from quirebase.access import (
    ResourceAction,
    WorkspaceContext,
    require_action,
)
from quirebase.core.errors import ValidationFailure
from quirebase.core.persistence import select_page
from quirebase.models import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
)

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
        )
        .order_by(Workspace.name, Workspace.id)
    )
    filters: list[StatementFilter] = (
        [LimitOffset(limit=limit, offset=offset)] if limit is not None else []
    )
    if search.strip():
        filters.append(SearchFilter(field_name="name", value=search.strip(), ignore_case=True))
    roots, total = await select_page(
        db,
        query,
        Workspace,
        *filters,
    )
    if not roots:
        return [], total
    members = {
        member.workspace_id: member
        for member in await db.scalars(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id.in_([workspace.id for workspace in roots]),
                WorkspaceMember.user_id == actor.id,
                WorkspaceMember.state == WorkspaceMemberState.active,
                WorkspaceMember.terminated_at.is_(None),
            )
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
            owner_count == 1,
        )
        .correlate(Workspace)
        .scalar_subquery()
    )
    return select(Workspace.id, owner_id.label("owner_id"))


async def workspace_owner_ids(db: AsyncSession, workspace_ids: set[UUID]) -> dict[UUID, UUID]:
    """Return structural owners; an inactive User retains its ownership assignment."""
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
        f"Workspace {workspace_id} must have exactly one current active owner membership"
        for workspace_id, owner_id in rows
        if owner_id is None
    ]


async def workspace_owners(db: AsyncSession, workspace_ids: set[UUID]) -> dict[UUID, User]:
    """Project owner identity and account status from the structural owner query."""
    if not workspace_ids:
        return {}
    owners = _workspace_owners_query().where(Workspace.id.in_(workspace_ids)).subquery()
    rows = (
        await db.execute(select(owners.c.id, User).outerjoin(User, User.id == owners.c.owner_id))
    ).all()
    missing = {workspace_id for workspace_id, user in rows if user is None}
    if missing:
        raise RuntimeError(f"Workspace owner invariant failed for: {sorted(missing)}")
    return {workspace_id: user for workspace_id, user in rows if user is not None}


async def list_workspace_members(
    db: AsyncSession,
    context: WorkspaceContext,
    *,
    limit: int = 25,
    offset: int = 0,
    search: str = "",
    role: WorkspaceRole | Literal[""] = "",
    direction: Literal["asc", "desc"] = "asc",
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
    return await _member_page(db, query, limit, offset, search, role=role, direction=direction)


async def list_workspace_governance_members(
    db: AsyncSession,
    context: WorkspaceContext,
    *,
    limit: int = 25,
    offset: int = 0,
    search: str = "",
    role: WorkspaceRole | Literal[""] = "",
    state: WorkspaceMemberState | Literal[""] = "",
    sort: Literal["username", "joined"] = "username",
    direction: Literal["asc", "desc"] = "asc",
) -> tuple[list[WorkspaceMember], int]:
    require_action(context, ResourceAction.workspace_membership_read)
    query = (
        select(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(
            WorkspaceMember.workspace_id == context.workspace_id,
            WorkspaceMember.terminated_at.is_(None),
        )
    )
    if state:
        if state not in WorkspaceMemberState:
            raise ValidationFailure(f"unknown Workspace membership state: {state}")
        query = query.where(WorkspaceMember.state == state)
    return await _member_page(
        db, query, limit, offset, search, role=role, sort=sort, direction=direction
    )


async def _member_page(
    db: AsyncSession,
    query: Select[tuple[WorkspaceMember]],
    limit: int,
    offset: int,
    search: str,
    *,
    role: WorkspaceRole | Literal[""] = "",
    sort: Literal["username", "joined"] = "username",
    direction: Literal["asc", "desc"] = "asc",
) -> tuple[list[WorkspaceMember], int]:
    columns = {"username": User.username, "joined": WorkspaceMember.created_at}
    if sort not in columns:
        raise ValidationFailure(f"unknown Workspace member sort: {sort}")
    if direction not in {"asc", "desc"}:
        raise ValidationFailure(f"unknown sort direction: {direction}")
    if role:
        if role not in WorkspaceRole:
            raise ValidationFailure(f"unknown Workspace role: {role}")
        query = query.where(WorkspaceMember.role == role)
    if search.strip():
        matching_users = SearchFilter(field_name="username", value=search.strip(), ignore_case=True)
        query = query.where(
            WorkspaceMember.user_id.in_(matching_users.append_to_statement(select(User.id), User))
        )
    records, total = await select_page(
        db,
        query,
        WorkspaceMember,
        LimitOffset(limit=limit, offset=offset),
        OrderBy(field_name=columns[sort], sort_order=direction),
        OrderBy(field_name="id", sort_order=direction),
    )
    return list(records), total
