from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ToolEffect(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    OPEN_WORLD_READ = "open_world_read"
    OPEN_WORLD_WRITE = "open_world_write"


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
        "workspaces.get_workspaces",
        "List the User's accessible Workspaces, IDs, roles and authorization; start here before choosing workspace_id.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "workspaces.get_user_workspace",
        "Get the selected Workspace's current role, lifecycle, freeze state and authorization.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "workspaces.get_workspace_members",
        "Search the selected Workspace's member directory by username or role before choosing Project participants.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "imports.import_batches",
        "List pending Import Batches or completed confirmation receipts in the selected Workspace.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "imports.stage_identifiers_import",
        "Look up DOI, PMID, arXiv or other identifiers through a Provider and stage an Import Batch for review; creates no Items. Review records and diagnostics before explicitly confirming with imports.commit_staged_import.",
        ToolEffect.OPEN_WORLD_WRITE,
    ),
    McpToolDefinition(
        "imports.import_batch",
        "Get an Import Batch preview, diagnostics and preview_version, or its committed Item IDs; never returns staged file bytes or storage keys.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "imports.commit_staged_import",
        "Confirm a reviewed Import Batch after the User explicitly approves it; returns committed Item IDs. For ready PDF batches supply the reviewed preview_version as expected_preview_version and explicitly selected basic_source_ids. Confirmation replays the receipt while it exists.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "imports.delete_import",
        "Discard an unconfirmed Import Batch or delete a completed receipt. Imported Items remain; deleting a receipt ends confirmation replay and import_batch Library filtering.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "library.search_items",
        "Search Workspace Items by metadata and extracted PDF text; filter by Tag or Project, sort and paginate. Returns Item summaries, not full text or matching passages.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "library.get_item_facets",
        "Count author-name, keyword and Reference Type facets over filtered Items in the explicitly specified Workspace.",
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
        "Replace editable Item metadata using expected_version from a fresh read. Preserve metadata fields outside the requested changes; reread after a version conflict.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "items.item_organize",
        "Get an Item's assigned Tags and Projects, Tag recommendations and authorization before editing organization or checking the result.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "items.delete_library_item",
        "Permanently delete a canonical Workspace Item and its associated content; requires item.delete authority, not just removal from a Project.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "tools.citation_styles",
        "Search available builtin and Workspace-custom Citation Styles and their keys before formatting an Item citation.",
        ToolEffect.READ,
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
        "Get a Project's settings, participation and active participants. Read its Items separately with library.search_items(project=project_id).",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "projects.create_user_project",
        "Create a Project in the explicitly specified Workspace.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "projects.update_project",
        "Update a Project's name, description, and participation in one operation.",
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
        "projects.remove_project_item",
        "Remove an Item from a Project, permanently deleting its Project Annotations and Replies.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "projects.join_project_api",
        "Join an open Project as the authenticated User; Workspace-mode participation is implicit and managed Projects require governance.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "projects.leave_project_api",
        "Leave an open Project as the authenticated User, removing that participation while preserving canonical Workspace Items.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "projects.add_project_participant", "Add a managed Project participant.", ToolEffect.WRITE
    ),
    McpToolDefinition(
        "projects.remove_project_participant",
        "Remove a managed Project participant.",
        ToolEffect.DESTRUCTIVE,
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
        "List visible Annotations and embedded Replies across an Item's File Revisions. Optionally filter by revision_id, private or Project scope and Projects; use cursor pagination to traverse while content changes.",
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
        "Soft-delete an editable Annotation with version checking; retain its ID and incremented version for restoration within the undo window.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "annotations.restore_annotation",
        "Restore the User's recently deleted Annotation within the undo window, using its post-deletion version (the deleted version plus one).",
        ToolEffect.WRITE,
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
        "Soft-delete an editable Annotation Reply with version checking; retain its ID and incremented version for restoration within the undo window.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "annotations.restore_reply",
        "Restore the User's recently deleted Annotation Reply within the undo window, using its post-deletion version (the deleted version plus one).",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "library.list_tags", "List visible Tags with visible Item counts.", ToolEffect.READ
    ),
    McpToolDefinition(
        "tools.duplicate_items",
        "Explicitly find duplicate Item groups by shared identifier, title or file; never automatically merges or deletes Items.",
        ToolEffect.READ,
    ),
    McpToolDefinition(
        "tools.rename_user_tag",
        "Rename a Workspace Tag while preserving its Item assignments.",
        ToolEffect.WRITE,
    ),
    McpToolDefinition(
        "tools.merge_user_tags",
        "Merge a source Workspace Tag into a target Tag, preserving assignments under the target and deleting the source Tag.",
        ToolEffect.DESTRUCTIVE,
    ),
    McpToolDefinition(
        "tools.delete_user_tag",
        "Delete a Workspace Tag and all of its Item assignments; preserves Items. To detach one Item use library.remove_item_tag instead.",
        ToolEffect.DESTRUCTIVE,
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
        "discovery.discovery_providers",
        "List the deployment's available Discovery and Identifier Lookup Providers, supported sorting and identifier namespaces before selecting a Provider.",
        ToolEffect.READ,
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
