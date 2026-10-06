from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING
from uuid import UUID

from advanced_alchemy.filters import LimitOffset
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from sqlalchemy import delete, inspect, or_, select
from sqlalchemy.exc import IntegrityError

from quirebase.access import SystemAction, require_system_action
from quirebase.audit import record_event
from quirebase.core.crypto import hash_password_async
from quirebase.core.errors import (
    PermissionDenied,
    ResourceNotFound,
    ValidationFailure,
)
from quirebase.models import (
    Invitation,
    LoginSession,
    SystemRole,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from quirebase.workspaces import provision_initial_workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement


class UserReadRepository(SQLAlchemyAsyncRepository[User]):
    model_type = User


async def list_users(db: AsyncSession, admin: User) -> list[User]:
    await require_system_action(db, admin, SystemAction.users_read)
    return list((await db.scalars(select(User).order_by(User.username))).all())


async def list_users_paginated(
    db: AsyncSession,
    admin: User,
    search: str = "",
    role: str = "",
    active: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[User], int]:
    await require_system_action(db, admin, SystemAction.users_read)
    query = select(User)
    filters = []
    if search.strip():
        term = f"%{search.strip()}%"
        matches: list[ColumnElement[bool]] = [User.username.ilike(term)]
        with contextlib.suppress(ValueError):
            matches.append(User.id == UUID(search.strip()))
        filters.append(or_(*matches))
    if role.strip() and role in ("administrator", "member"):
        filters.append(User.role == role)
    if active is not None:
        filters.append(User.active == active)
    if filters:
        query = query.where(*filters)
    offset = max(0, (page - 1) * page_size)
    return await UserReadRepository(
        session=db, statement=query.order_by(User.username, User.id)
    ).get_many_and_count(
        LimitOffset(limit=page_size, offset=offset),
        count_with_window_function=False,
    )


async def _lock_admin_and_target(
    db: AsyncSession,
    admin: User,
    user_id: UUID,
    action: SystemAction,
) -> tuple[User, User | None]:
    """Lock the authority source and mutated User in stable identity order."""

    identity = inspect(admin).identity
    admin_id = identity[0] if identity else admin.id
    locked: dict[UUID, User] = {}
    for current_id in sorted({admin_id, user_id}):
        query = select(User).where(User.id == current_id).execution_options(populate_existing=True)
        if current_id == user_id:
            # Account mutations do not change an FK-referenced key, so NO KEY
            # UPDATE is the narrow write lock required by the User aggregate.
            query = query.with_for_update(key_share=True)
        else:
            query = query.with_for_update(read=True)
        current = await db.scalar(query)
        if current is not None:
            locked[current_id] = current

    current_admin = await require_system_action(db, locked.get(admin_id, admin), action)
    return current_admin, locked.get(user_id)


async def create_user_admin(
    db: AsyncSession, admin: User, username: str, password: str, role: str = "member"
) -> User:
    await require_system_action(db, admin, SystemAction.users_create)
    cleaned_name = username.strip()
    if not cleaned_name or len(cleaned_name) > 120:
        raise ValidationFailure("username must contain 1 to 120 characters")
    if len(password) < 12:
        raise ValidationFailure("password must contain at least 12 characters")
    if role not in (SystemRole.administrator.value, SystemRole.member.value):
        raise ValidationFailure("invalid user role")
    existing = await db.scalar(select(User).where(User.username == cleaned_name))
    if existing is not None:
        raise ValidationFailure(f"username '{cleaned_name}' is already taken")
    password_hash = await hash_password_async(password)
    admin = await require_system_action(db, admin, SystemAction.users_create, lock="shared")
    existing = await db.scalar(select(User).where(User.username == cleaned_name))
    if existing is not None:
        raise ValidationFailure(f"username '{cleaned_name}' is already taken")
    user = User(
        username=cleaned_name,
        password_hash=password_hash,
        role=role,
        active=True,
    )
    db.add(user)
    try:
        await db.flush()
        await provision_initial_workspace(db, user)
        record_event(
            db,
            admin.id,
            "admin.user.create",
            "user",
            user.id,
            detail={"username": user.username, "role": user.role},
            authorization_resource_action=SystemAction.users_create.value,
        )
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise ValidationFailure(f"username '{cleaned_name}' is already taken") from error
    return user


async def update_user_status(db: AsyncSession, admin: User, user_id: UUID, active: bool) -> User:
    admin, user = await _lock_admin_and_target(db, admin, user_id, SystemAction.users_status_manage)
    if user is None:
        raise ResourceNotFound("user not found")
    if user.id == admin.id and not active:
        raise PermissionDenied("administrators cannot deactivate their own account")
    if not active and await db.scalar(
        select(Workspace.id)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.role == WorkspaceRole.owner,
            WorkspaceMember.terminated_at.is_(None),
            Workspace.state != "deleted",
        )
    ):
        raise PermissionDenied("transfer Workspace ownership before deactivating this account")
    if not active:
        # Lock every Workspace where the account is still a member so deactivation cannot race
        # Workspace ownership transfer or membership termination.
        workspace_ids = set(
            (
                await db.scalars(
                    select(Workspace.id)
                    .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                    .where(
                        WorkspaceMember.user_id == user.id,
                        WorkspaceMember.terminated_at.is_(None),
                    )
                )
            ).all()
        )
        for workspace_id in sorted(workspace_ids):
            await db.scalar(
                select(Workspace.id).where(Workspace.id == workspace_id).with_for_update()
            )
        if await db.scalar(
            select(Workspace.id)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.role == WorkspaceRole.owner,
                WorkspaceMember.terminated_at.is_(None),
                Workspace.state != "deleted",
            )
        ):
            raise PermissionDenied("transfer Workspace ownership before deactivating this account")
    user.active = active
    if not active:
        # Revoke all active sessions upon deactivation
        await db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    record_event(
        db,
        admin.id,
        "admin.user.status_update",
        "user",
        user.id,
        detail={"active": active},
        authorization_resource_action=SystemAction.users_status_manage.value,
    )
    await db.commit()
    return user


async def change_user_role(db: AsyncSession, admin: User, user_id: UUID, new_role: str) -> User:
    if new_role not in (SystemRole.administrator.value, SystemRole.member.value):
        raise ValidationFailure("invalid user role")
    admin, user = await _lock_admin_and_target(db, admin, user_id, SystemAction.users_roles_manage)
    if user is None:
        raise ResourceNotFound("user not found")
    if user.id == admin.id and new_role != SystemRole.administrator.value:
        raise PermissionDenied("administrators cannot demote their own account")
    user.role = new_role
    record_event(
        db,
        admin.id,
        "admin.user.role_change",
        "user",
        user.id,
        detail={"new_role": new_role},
        authorization_resource_action=SystemAction.users_roles_manage.value,
    )
    await db.commit()
    return user


async def reset_user_password(
    db: AsyncSession, admin: User, user_id: UUID, new_password: str
) -> None:
    await require_system_action(db, admin, SystemAction.users_password_reset)
    if len(new_password) < 12:
        raise ValidationFailure("password must contain at least 12 characters")
    if not await db.scalar(select(User.id).where(User.id == user_id)):
        raise ResourceNotFound("user not found")
    password_hash = await hash_password_async(new_password)
    admin, user = await _lock_admin_and_target(
        db, admin, user_id, SystemAction.users_password_reset
    )
    if user is None:
        raise ResourceNotFound("user not found")
    user.password_hash = password_hash
    # Revoke sessions after password reset
    await db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    record_event(
        db,
        admin.id,
        "admin.user.password_reset",
        "user",
        user.id,
        authorization_resource_action=SystemAction.users_password_reset.value,
    )
    await db.commit()


async def revoke_user_sessions(db: AsyncSession, admin: User, user_id: UUID) -> int:
    admin = await require_system_action(
        db, admin, SystemAction.users_sessions_revoke, lock="shared"
    )
    user = await db.get(User, user_id)
    if user is None:
        raise ResourceNotFound("user not found")
    result = await db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    deleted_count = result.rowcount if hasattr(result, "rowcount") else 1
    record_event(
        db,
        admin.id,
        "admin.user.sessions_revoked",
        "user",
        user.id,
        authorization_resource_action=SystemAction.users_sessions_revoke.value,
    )
    await db.commit()
    return deleted_count


async def list_invitations(db: AsyncSession, admin: User) -> list[Invitation]:
    await require_system_action(db, admin, SystemAction.invitations_read)
    return list((await db.scalars(select(Invitation).order_by(Invitation.created_at.desc()))).all())
