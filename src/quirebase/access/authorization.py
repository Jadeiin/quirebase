from __future__ import annotations

import csv
from enum import Enum, StrEnum
from functools import lru_cache
from itertools import pairwise
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
_WORKSPACE_LIFECYCLES = frozenset({"active", "archived", "suspended"})
_EXPECTED_ROLE_EDGES = frozenset({
    ("workspace:owner", "workspace:admin"),
    ("workspace:admin", "workspace:editor"),
    ("workspace:editor", "workspace:reviewer"),
    ("workspace:reviewer", "workspace:viewer"),
    ("system:administrator", "system:member"),
})


class ResourceActionKey(StrEnum):
    """Canonical dotted serialization of one Casbin resource/action pair."""

    @property
    def resource(self) -> str:
        return self.value.partition(".")[0]

    @property
    def action(self) -> str:
        return self.value.partition(".")[2]


class SystemAction(ResourceActionKey):
    account_change_password = "account.change_password"
    api_tokens_create = "api_token.create"
    api_tokens_read = "api_token.read"
    api_tokens_revoke = "api_token.revoke"
    login_sessions_read = "login_session.read"
    login_sessions_revoke = "login_session.revoke"
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
    workspace_invitations_accept = "workspace_invitation.accept"
    workspaces_governance_read = "workspace_governance.read"
    workspaces_governance_suspend = "workspace_governance.suspend"
    workspaces_governance_recover = "workspace_governance.recover"
    workspaces_break_glass_read = "workspace_break_glass.read"


# Accepted request facts, not grants. The immutable policy bundle owns allow/deny.
SYSTEM_POLICY_RELATIONS: dict[SystemAction, tuple[str, ...]] = dict.fromkeys(SystemAction, ("any",))
for _own_action in (
    SystemAction.account_change_password,
    SystemAction.api_tokens_create,
    SystemAction.api_tokens_read,
    SystemAction.api_tokens_revoke,
    SystemAction.login_sessions_read,
    SystemAction.login_sessions_revoke,
    SystemAction.workspace_invitations_accept,
):
    SYSTEM_POLICY_RELATIONS[_own_action] = ("own",)
SYSTEM_POLICY_RELATIONS[SystemAction.workspaces_create] = ("members_allowed", "admins_only")


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

    from quirebase.access.workspace_policy import validate_action_specs

    validate_action_specs()
    _enforcer()
    _validate_policy_bundle()


@lru_cache(maxsize=1)
def _validate_policy_bundle() -> None:
    from quirebase.access.workspace_policy import ResourceAction, action_spec

    workspace_actions = {action.value for action in ResourceAction}
    system_actions = {action.value for action in SystemAction}
    workspace_relations = {
        relation for action in ResourceAction for relation in action_spec(action).policy_relations
    }
    system_relations = {
        relation for relations in SYSTEM_POLICY_RELATIONS.values() for relation in relations
    }
    known_actions = workspace_actions | system_actions
    workspace_roles = tuple(WorkspaceRole)
    system_roles = tuple(SystemRole)
    expected_subjects = {
        *(f"workspace:{role.value}" for role in workspace_roles),
        *(f"system:{role.value}" for role in system_roles),
    }
    policy_actions: set[str] = set()
    role_edges: set[tuple[str, str]] = set()
    for line_number, raw_line in enumerate(_POLICY_PATH.read_text().splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        row = [field.strip() for field in next(csv.reader([raw_line], skipinitialspace=True))]
        if row[0] == "g":
            if len(row) != 3:
                raise RuntimeError(f"invalid Casbin role rule on policy.csv:{line_number}")
            role_edges.add((row[1], row[2]))
            continue
        if row[0] != "p" or len(row) != 6:
            raise RuntimeError(f"invalid Casbin policy rule on policy.csv:{line_number}")

        subject, resource, action, lifecycle, relation = row[1:]
        key = f"{resource}.{action}"
        if subject not in expected_subjects:
            raise RuntimeError(f"unknown Casbin subject {subject!r} on policy.csv:{line_number}")
        if key not in known_actions:
            raise RuntimeError(f"unknown resource-action {key!r} on policy.csv:{line_number}")
        policy_actions.add(key)

        def alternatives(value: str) -> set[str]:
            if value.startswith("(") and value.endswith(")"):
                return set(value[1:-1].split("|"))
            return {value}

        if subject.startswith("workspace:"):
            if key not in workspace_actions:
                raise RuntimeError(f"system action {key!r} used by {subject!r}")
            if not alternatives(lifecycle) <= _WORKSPACE_LIFECYCLES:
                raise RuntimeError(
                    f"unknown Workspace lifecycle {lifecycle!r} on policy.csv:{line_number}"
                )
            if not alternatives(relation) <= workspace_relations:
                raise RuntimeError(
                    f"unknown Workspace relation {relation!r} on policy.csv:{line_number}"
                )
            accepted_relations = action_spec(ResourceAction(key)).policy_relations
        else:
            if key not in system_actions:
                raise RuntimeError(f"Workspace action {key!r} used by {subject!r}")
            if lifecycle != "active":
                raise RuntimeError(
                    f"invalid System lifecycle {lifecycle!r} on policy.csv:{line_number}"
                )
            if not alternatives(relation) <= system_relations:
                raise RuntimeError(
                    f"unknown System relation {relation!r} on policy.csv:{line_number}"
                )

            accepted_relations = SYSTEM_POLICY_RELATIONS[SystemAction(key)]
        if not alternatives(relation) <= set(accepted_relations):
            raise RuntimeError(
                f"invalid relation {relation!r} for {key!r} on policy.csv:{line_number}"
            )

    if role_edges != _EXPECTED_ROLE_EDGES:
        raise RuntimeError("Casbin role inheritance does not match the canonical role hierarchy")
    missing_actions = known_actions - policy_actions
    if missing_actions:
        raise RuntimeError(f"authorization actions have no policy: {sorted(missing_actions)}")

    workspace_facts = {
        (action.resource, action.action, lifecycle, relation)
        for action in ResourceAction
        for lifecycle in _WORKSPACE_LIFECYCLES
        for relation in workspace_relations
    }
    ordered_workspace_roles = tuple(reversed(workspace_roles))
    for lower, higher in pairwise(ordered_workspace_roles):
        for resource, action, lifecycle, relation in workspace_facts:
            if _enforce(
                _workspace_subject(lower), resource, action, lifecycle, relation
            ) and not _enforce(_workspace_subject(higher), resource, action, lifecycle, relation):
                raise RuntimeError(
                    f"Workspace role {higher.value!r} is not monotonic over {lower.value!r}"
                )

    system_facts = {
        (action.resource, action.action, relation)
        for action in SystemAction
        for relation in system_relations
    }
    for resource, action, relation in system_facts:
        if _enforce(
            _system_subject(SystemRole.member), resource, action, "active", relation
        ) and not _enforce(
            _system_subject(SystemRole.administrator), resource, action, "active", relation
        ):
            raise RuntimeError("System role administrator is not monotonic over member")


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
