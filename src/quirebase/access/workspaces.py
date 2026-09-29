from __future__ import annotations

"""Public Workspace access exports; implementations live in focused access modules."""

from quirebase.access.context import (
    ProjectContext,
    WorkspaceContext,
    require_action,
    require_workspace_action,
    require_workspace_membership,
    resolve_workspace_context,
)
from quirebase.access.project_scope import (
    require_project_access,
    require_project_context,
    visible_project_ids_query,
)
from quirebase.access.workspace_policy import (
    ResourceAction,
    action_allowed,
    effective_resource_action_relations,
    effective_resource_actions,
    workspace_member_relation,
    workspace_resource_action_allowed,
)

__all__ = [
    "ProjectContext",
    "ResourceAction",
    "WorkspaceContext",
    "action_allowed",
    "effective_resource_action_relations",
    "effective_resource_actions",
    "require_action",
    "require_project_access",
    "require_project_context",
    "require_workspace_action",
    "require_workspace_membership",
    "resolve_workspace_context",
    "visible_project_ids_query",
    "workspace_member_relation",
    "workspace_resource_action_allowed",
]
