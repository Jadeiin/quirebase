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
        "library.search",
        "Search bibliographic Items visible to the authenticated User.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "library.get_item",
        "Get bibliographic metadata for one visible Item; never returns file content.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "library.create_item",
        "Create a bibliographic Item owned by the authenticated User.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "library.update_item",
        "Replace editable Item metadata using optimistic version checking.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "citations.format_item",
        "Render a visible Item as a plain-text or HTML citation.",
        ToolEffect.READ,
    ),
    McpToolDefinition("projects.list", "List joined Projects.", ToolEffect.READ),
    McpToolDefinition(
        "projects.get",
        "Get one joined Project, its members, and bibliographic Items.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "projects.create", "Create a Project owned by the authenticated User.", ToolEffect.WRITE
    ),
    McpToolDefinition(
        "projects.update_settings",
        "Update a Project's name, description, and visibility in one operation.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition("projects.delete", "Permanently delete a Project.", ToolEffect.DESTRUCTIVE),
    McpToolDefinition("projects.archive", "Archive a Project.", ToolEffect.WRITE),
    McpToolDefinition("projects.restore", "Restore an archived Project.", ToolEffect.WRITE),
    McpToolDefinition("projects.leave", "Leave a Project.", ToolEffect.WRITE),
    McpToolDefinition(
        "projects.transfer_ownership",
        "Transfer Project ownership to an existing member.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition("projects.add_item", "Add a visible Item to a Project.", ToolEffect.WRITE),
    McpToolDefinition(
        "projects.remove_item", "Remove an Item from a Project.", ToolEffect.DESTRUCTIVE
    ),
    McpToolDefinition(
        "projects.set_member", "Add or change a Project editor or viewer.", ToolEffect.WRITE
    ),
    McpToolDefinition("projects.remove_member", "Remove a Project member.", ToolEffect.DESTRUCTIVE),
    McpToolDefinition(
        "documents.list",
        "List revision and attachment metadata for a visible Item; no file bytes or text.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "annotations.list", "List visible Annotations for one File Revision.", ToolEffect.READ
    ),
    McpToolDefinition(
        "annotations.create", "Create a private or Project-visible Annotation.", ToolEffect.WRITE
    ),
    McpToolDefinition(
        "annotations.update",
        "Update an editable Annotation using optimistic version checking.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "annotations.delete", "Soft-delete an editable Annotation.", ToolEffect.DESTRUCTIVE
    ),
    McpToolDefinition(
        "annotation_replies.create", "Reply to a visible Annotation.", ToolEffect.WRITE
    ),
    McpToolDefinition(
        "annotation_replies.update",
        "Update an editable Annotation Reply using optimistic version checking.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "annotation_replies.delete",
        "Soft-delete an editable Annotation Reply.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition("tags.list", "List Tags with visible Item counts.", ToolEffect.READ),
    McpToolDefinition("tags.add_to_item", "Add a Tag to an editable Item.", ToolEffect.WRITE),
    McpToolDefinition(
        "tags.remove_from_item", "Remove a Tag from an editable Item.", ToolEffect.DESTRUCTIVE
    ),
    McpToolDefinition(
        "tags.set_for_item", "Reconcile the Tag selection for an editable Item.", ToolEffect.WRITE
    ),
    McpToolDefinition(
        "discussions.list", "List Discussion Messages for a visible Item.", ToolEffect.READ
    ),
    McpToolDefinition(
        "discussions.add", "Add a Discussion Message to a visible Item.", ToolEffect.WRITE
    ),
    McpToolDefinition(
        "discussions.delete",
        "Delete the User's own Discussion Message.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "discovery.search",
        "Search an external scholarly metadata Provider; never forwards the API Token upstream.",
        ToolEffect.OPEN_WORLD_READ,
    ),
)

MCP_TOOLS = {definition.operation_id: definition for definition in _DEFINITIONS}
TOOL_ALLOWLIST = frozenset(MCP_TOOLS)


__all__ = ["MCP_TOOLS", "TOOL_ALLOWLIST", "McpToolDefinition", "ToolEffect"]
