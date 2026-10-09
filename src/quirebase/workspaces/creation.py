from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.access import (
    SystemAction,
    system_action_allowed,
)
from quirebase.audit import record_event
from quirebase.core.errors import (
    PermissionDenied,
    ResourceNotFound,
    ValidationFailure,
)
from quirebase.models import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
)
from quirebase.operations.settings import get_effective_setting

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _workspace_name(user: User) -> str:
    return f"{user.username}'s Workspace"


async def provision_initial_workspace(db: AsyncSession, user: User) -> Workspace:
    """Create the ordinary Workspace included in a new User's creation transaction."""
    locked = await db.scalar(
        select(User)
        .where(User.id == user.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if locked is None:
        raise ResourceNotFound("User not found")
    existing = await db.scalar(
        select(Workspace.id).where(Workspace.created_by == locked.id).limit(1)
    )
    if existing is not None:
        raise ValidationFailure("Workspace provisioning is only available during User creation")

    workspace = Workspace(name=_workspace_name(locked), created_by=locked.id)
    db.add(workspace)
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=locked.id,
            role=WorkspaceRole.owner,
            state=WorkspaceMemberState.active,
            invited_by=locked.id,
        )
    )
    record_event(
        db,
        locked.id,
        "workspace.provision",
        "workspace",
        workspace.id,
        workspace_id=workspace.id,
        authorization_role=WorkspaceRole.owner.value,
    )
    await db.flush()
    return workspace


def _can_create_workspace(user: User, policy: str) -> bool:
    return (
        user.active
        and policy in {"admins_only", "members_allowed"}
        and system_action_allowed(
            user.role,
            SystemAction.workspaces_create,
            relation=policy,
        )
    )


@dataclass(frozen=True)
class WorkspaceCreationOptions:
    allowed: bool
    owner_username_required: bool


async def workspace_creation_options(db: AsyncSession, actor: User) -> WorkspaceCreationOptions:
    policy = await get_effective_setting(db, "workspace_creation_policy", "admins_only")
    return WorkspaceCreationOptions(
        allowed=_can_create_workspace(actor, policy),
        owner_username_required=policy == "admins_only",
    )


async def create_workspace(
    db: AsyncSession,
    actor: User,
    name: str,
    *,
    owner_username: str | None = None,
) -> Workspace:
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 240:
        raise ValidationFailure("Workspace name must contain 1 to 240 characters")
    policy = await get_effective_setting(db, "workspace_creation_policy", "admins_only")
    if policy not in {"admins_only", "members_allowed"}:
        raise ValidationFailure("invalid Workspace creation policy")
    if not _can_create_workspace(actor, policy):
        raise PermissionDenied("Workspace creation is restricted by the instance policy")
    if policy == "members_allowed" and owner_username is not None:
        raise ValidationFailure("member-created Workspaces are owned by their creator")
    if policy == "admins_only" and owner_username is None:
        raise ValidationFailure("owner_username is required by the Workspace creation policy")

    cleaned_owner_username = owner_username.strip() if owner_username is not None else None
    if owner_username is not None and not cleaned_owner_username:
        raise ValidationFailure("Workspace owner username must not be empty")
    if owner_username is not None:
        requested_owner_id = await db.scalar(
            select(User.id).where(User.username == cleaned_owner_username, User.active.is_(True))
        )
        if requested_owner_id is None:
            raise ValidationFailure("Workspace owner username must match an active User")
    else:
        requested_owner_id = actor.id
    user_ids = {actor.id}
    user_ids.add(requested_owner_id)
    locked_users = {
        user.id: user
        for user in (
            await db.scalars(
                select(User)
                .where(User.id.in_(user_ids))
                .order_by(User.id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).all()
    }
    current_actor = locked_users.get(actor.id)
    if current_actor is None or not current_actor.active:
        raise PermissionDenied("active User required")
    if not _can_create_workspace(current_actor, policy):
        raise PermissionDenied("Workspace creation is restricted by the instance policy")
    owner = locked_users.get(requested_owner_id)
    if owner is None or not owner.active:
        raise ValidationFailure("Workspace owner must be an active User")
    workspace = Workspace(name=cleaned, created_by=actor.id)
    db.add(workspace)
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=owner.id,
            role=WorkspaceRole.owner,
            state=WorkspaceMemberState.active,
            invited_by=actor.id,
        )
    )
    record_event(
        db,
        actor.id,
        "workspace.create",
        "workspace",
        workspace.id,
        detail={
            "owner_user_id": owner.id,
            "owner_workspace_role": WorkspaceRole.owner.value,
            "creation_policy": policy,
        },
        workspace_id=workspace.id,
        authorization_role=current_actor.role,
        authorization_resource_action=SystemAction.workspaces_create.value,
    )
    await db.commit()
    return workspace
