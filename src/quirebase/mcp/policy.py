from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ToolEffect(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    OPEN_WORLD_READ = "open_world_read"


@dataclass(frozen=True)
class McpToolDefinition:
    operation_id: str
    description: str
    effect: ToolEffect

    @property
    def name(self) -> str:
        return self.operation_id


_DEFINITIONS = (
    McpToolDefinition(
        "library.search_items",
        "Search bibliographic Items in the explicitly specified Workspace.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "library.get_library_item",
        "Get bibliographic metadata for one Item in the explicitly specified Workspace; never returns file content.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "library.create_library_item",
        "Create a bibliographic Item in the explicitly specified Workspace.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "library.update_library_item",
        "Replace editable Item metadata using optimistic version checking.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "library.format_item_citation",
        "Render a visible Item as a plain-text or HTML citation.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "projects.list_projects",
        "List Projects in the explicitly specified Workspace.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "projects.get_project",
        "Get one Project in the explicitly specified Workspace, its members, and bibliographic Items.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "projects.create_user_project",
        "Create a Project in the explicitly specified Workspace.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "projects.update_project",
        "Update a Project's name, description, and visibility in one operation.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "projects.delete_user_project", "Permanently delete a Project.", ToolEffect.DESTRUCTIVE
    ),
    McpToolDefinition("projects.archive_project", "Archive a Project.", ToolEffect.WRITE),
    McpToolDefinition("projects.restore_project", "Restore an archived Project.", ToolEffect.WRITE),
    McpToolDefinition(
        "projects.add_project_item", "Add a visible Item to a Project.", ToolEffect.WRITE
    ),
    McpToolDefinition(
        "projects.remove_project_item", "Remove an Item from a Project.", ToolEffect.DESTRUCTIVE
    ),
    McpToolDefinition("projects.set_project_member", "Add a Project member.", ToolEffect.WRITE),
    McpToolDefinition(
        "projects.remove_project_member", "Remove a Project member.", ToolEffect.DESTRUCTIVE
    ),
    McpToolDefinition(
        "projects.list_project_discussions",
        "List Discussion Messages in a visible Project in the explicitly specified Workspace.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "projects.create_project_discussion",
        "Add a Discussion Message to a visible Project.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "projects.delete_project_discussion",
        "Delete the User's own Project Discussion Message.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "documents.list_documents",
        "List revision and attachment metadata for a visible Item; no file bytes or text.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "annotations.list_annotations",
        "List visible Annotations for one File Revision.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "annotations.create_annotation",
        "Create a private or Project-scoped Annotation in the explicitly specified Workspace.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "annotations.update_annotation",
        "Update an editable Annotation using optimistic version checking.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "annotations.delete_annotation",
        "Soft-delete an editable Annotation.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "annotations.create_reply", "Reply to a visible Annotation.", ToolEffect.WRITE
    ),
    McpToolDefinition(
        "annotations.update_reply",
        "Update an editable Annotation Reply using optimistic version checking.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "annotations.delete_reply",
        "Soft-delete an editable Annotation Reply.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "library.list_tags", "List visible Tags with visible Item counts.", ToolEffect.READ
    ),
    McpToolDefinition("library.add_item_tag", "Add a Tag to an editable Item.", ToolEffect.WRITE),
    McpToolDefinition(
        "library.remove_item_tag",
        "Remove a Tag from an editable Item.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "library.set_item_tag_selection",
        "Reconcile the Tag selection for an editable Item.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "library.list_discussions",
        "List Discussion Messages for a visible Item.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "library.create_discussion",
        "Add a Discussion Message to a visible Item.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "library.delete_discussion",
        "Delete the User's own Discussion Message.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "discovery.search_discovery",
        "Search an external scholarly metadata Provider; never forwards the API Token upstream.",
        ToolEffect.OPEN_WORLD_READ,
    ),
)

MCP_TOOLS = {definition.operation_id: definition for definition in _DEFINITIONS}
TOOL_ALLOWLIST = frozenset(MCP_TOOLS)


__all__ = ["MCP_TOOLS", "TOOL_ALLOWLIST", "McpToolDefinition", "ToolEffect"]
