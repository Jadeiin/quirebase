from __future__ import annotations

from enum import Enum, StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import casbin
from sqlalchemy import inspect, select

from quirebase.core.errors import DomainError, ResourceUnavailable
from quirebase.models import SystemRole, User, WorkspaceRole

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

_POLICY_DIR = Path(__file__).with_name("policy")
_MODEL_PATH = _POLICY_DIR / "model.conf"
_POLICY_PATH = _POLICY_DIR / "policy.csv"


class ResourceActionKey(StrEnum):
    """Canonical dotted serialization of one Casbin resource/action pair."""

    @property
    def resource(self) -> str:
        return self.value.partition(".")[0]

    @property
    def action(self) -> str:
        return self.value.partition(".")[2]


class SystemAction(ResourceActionKey):
    users_read = "user.read"
    users_create = "user.create"
    users_status_manage = "user.manage_status"
    users_roles_manage = "user.manage_role"
    users_password_reset = "user.reset_password"
    users_sessions_revoke = "user.revoke_sessions"
    invitations_read = "invitation.read"
    invitations_create = "invitation.create"
    audit_read = "audit.read"
    workflows_read = "workflow.read"
    settings_read = "setting.read"
    settings_manage = "setting.manage"
    storage_metrics_read = "storage_metrics.read"
    maintenance_run = "maintenance.run"
    backup_read = "backup.read"
    system_metrics_read = "system_metrics.read"
    workspaces_create = "workspace.create"
    workspaces_governance_read = "workspace_governance.read"
    workspaces_governance_suspend = "workspace_governance.suspend"
    workspaces_governance_recover = "workspace_governance.recover"
    workspaces_break_glass_read = "workspace_break_glass.read"


def _value(value: str | Enum) -> str:
    return str(value.value if isinstance(value, Enum) else value)


def _system_subject(role: str | SystemRole) -> str:
    return f"system:{_value(role)}"


def _workspace_subject(role: str | WorkspaceRole) -> str:
    return f"workspace:{_value(role)}"


@lru_cache(maxsize=1)
def _enforcer() -> casbin.Enforcer:
    return casbin.Enforcer(str(_MODEL_PATH), str(_POLICY_PATH))


def initialize_authorization() -> None:
    """Parse and load the immutable policy bundle before serving requests."""

    _enforcer()


def _enforce(
    subject: str,
    resource: str,
    action: str | Enum,
    lifecycle: str | Enum = "any",
    relation: str = "any",
) -> bool:
    return _enforce_canonical(subject, resource, _value(action), _value(lifecycle), relation)


@lru_cache(maxsize=4096)
def _enforce_canonical(
    subject: str, resource: str, action: str, lifecycle: str, relation: str
) -> bool:
    # The bundled policy is immutable; canonical request facts remain the full cache key.
    return bool(
        _enforcer().enforce(
            subject,
            resource,
            action,
            lifecycle,
            relation,
        )
    )


def workspace_action_allowed(
    role: str | WorkspaceRole,
    resource: str,
    action: str | Enum,
    lifecycle: str | Enum,
    relation: str = "any",
) -> bool:
    return _enforce(_workspace_subject(role), resource, action, lifecycle, relation)


def system_action_allowed(
    role: str | SystemRole,
    action: SystemAction,
    *,
    relation: str = "any",
) -> bool:
    return _enforce(
        _system_subject(role),
        action.resource,
        action.action,
        "active",
        relation,
    )


def system_resource_action_allowed(
    role: str | SystemRole,
    resource: str,
    action: str,
    *,
    relation: str = "any",
) -> bool:
    return _enforce(_system_subject(role), resource, action, "active", relation)


@lru_cache(maxsize=16)
def effective_system_actions(role: str | SystemRole) -> frozenset[SystemAction]:
    return frozenset(action for action in SystemAction if system_action_allowed(role, action))


async def require_system_action(
    db: AsyncSession,
    actor: User,
    action: SystemAction,
    *,
    lock: Literal["shared", "write"] | None = None,
    message: str = "administrator required",
    denied_error: type[DomainError] = ResourceUnavailable,
) -> User:
    """Re-read the authenticated User and authorize one instance action.

    Mutations request a shared lock so role revocation cannot commit between
    this decision and the caller's transaction commit. A command that mutates
    the User itself requests a write lock at its linearization point.
    """

    return await _require_current_system_decision(
        db,
        actor,
        lambda current: system_action_allowed(current.role, action),
        lock=lock,
        message=message,
        denied_error=denied_error,
    )


async def _require_current_system_decision(
    db: AsyncSession,
    actor: User,
    allowed: Callable[[User], bool],
    *,
    lock: Literal["shared", "write"] | None,
    message: str,
    denied_error: type[DomainError],
) -> User:
    """Re-read the current User before trusting an instance authorization decision."""

    actor_identity = inspect(actor).identity
    actor_id = actor_identity[0] if actor_identity else actor.id
    query = select(User).where(User.id == actor_id).execution_options(populate_existing=True)
    if lock == "shared":
        query = query.with_for_update(read=True)
    elif lock == "write":
        query = query.with_for_update(key_share=True)
    current = await db.scalar(query)
    if current is None or not current.active or not allowed(current):
        raise denied_error(message)
    return current


async def require_system_resource_action(
    db: AsyncSession,
    actor: User,
    resource: str,
    action: str,
    *,
    relation: str = "any",
    lock: Literal["shared", "write"] | None = None,
    message: str = "resource unavailable",
    denied_error: type[DomainError] = ResourceUnavailable,
) -> User:
    return await _require_current_system_decision(
        db,
        actor,
        lambda current: system_resource_action_allowed(
            current.role,
            resource,
            action,
            relation=relation,
        ),
        lock=lock,
        message=message,
        denied_error=denied_error,
    )
