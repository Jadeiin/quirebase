from __future__ import annotations

from quirebase.access.annotations import can_edit_annotation, require_editable_annotation
from quirebase.access.documents import require_attachment, require_revision
from quirebase.access.items import (
    can_delete_item,
    can_edit_item,
    can_read_item,
    get_item,
    get_item_for_update,
    require_accessible_items,
    require_editable_item,
    require_readable_item,
    visible_items_query,
    workspace_items_query,
)
from quirebase.access.projects import (
    editable_projects,
    project_member,
    require_project_member,
    visible_projects,
    visible_projects_for_context,
)
from quirebase.access.scope import workspace_id_predicate, workspace_select
from quirebase.access.tags import visible_tags_query
from quirebase.access.workspaces import (
    ROLE_CAPABILITIES,
    Capability,
    ProjectContext,
    WorkspaceContext,
    require,
    require_project_access,
    require_project_context,
    require_workspace_capability,
    require_workspace_membership,
    resolve_workspace_context,
    role_has_capability,
)

__all__ = [
    "ROLE_CAPABILITIES",
    "Capability",
    "ProjectContext",
    "WorkspaceContext",
    "can_delete_item",
    "can_edit_annotation",
    "can_edit_item",
    "can_read_item",
    "editable_projects",
    "get_item",
    "get_item_for_update",
    "project_member",
    "require",
    "require_accessible_items",
    "require_attachment",
    "require_editable_annotation",
    "require_editable_item",
    "require_project_access",
    "require_project_context",
    "require_project_member",
    "require_readable_item",
    "require_revision",
    "require_workspace_capability",
    "require_workspace_membership",
    "resolve_workspace_context",
    "role_has_capability",
    "visible_items_query",
    "visible_projects",
    "visible_projects_for_context",
    "visible_tags_query",
    "workspace_id_predicate",
    "workspace_items_query",
    "workspace_select",
]
