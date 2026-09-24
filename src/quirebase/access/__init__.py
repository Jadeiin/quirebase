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
from quirebase.access.scope import workspace_id_predicate, workspace_select
from quirebase.access.tags import visible_tags_query
from quirebase.access.workspaces import (
    ROLE_CAPABILITIES,
    Capability,
    ProjectContext,
    WorkspaceContext,
    effective_capabilities,
    require,
    require_project_access,
    require_project_context,
    require_workspace_capability,
    require_workspace_membership,
    resolve_workspace_context,
    role_has_capability,
    visible_project_ids_query,
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
    "effective_capabilities",
    "get_item",
    "get_item_for_update",
    "require",
    "require_accessible_items",
    "require_attachment",
    "require_editable_annotation",
    "require_editable_item",
    "require_project_access",
    "require_project_context",
    "require_readable_item",
    "require_revision",
    "require_workspace_capability",
    "require_workspace_membership",
    "resolve_workspace_context",
    "role_has_capability",
    "visible_items_query",
    "visible_project_ids_query",
    "visible_tags_query",
    "workspace_id_predicate",
    "workspace_items_query",
    "workspace_select",
]
