from __future__ import annotations

from typing import TYPE_CHECKING

from quirebase.library import (
    DiscussionWorkspace,
    WorkspaceSection,
    add_discussion_message,
    add_tag_to_item,
    delete_discussion_message,
    list_accessible_tags_with_counts,
    open_item_workspace,
    remove_tag_from_item,
    set_item_tags,
)
from quirebase.mcp.tools.annotations import DESTRUCTIVE, READ_ONLY, WRITE
from quirebase.programmatic import (
    DiscussionMessageView,
    TagView,
    WriteResult,
    discussion_message_views,
)

if TYPE_CHECKING:
    from mcp.server import MCPServer

    from quirebase.mcp.runtime import McpRuntime


def register_organization_tools(server: MCPServer, runtime: McpRuntime) -> None:
    @server.tool(
        name="tags.list", description="List Tags with visible Item counts.", annotations=READ_ONLY
    )
    def tags_list() -> list[TagView]:
        return runtime.call(
            "tags.list",
            lambda db, user: [
                TagView(id=tag.id, name=tag.name, accessible_item_count=count)
                for tag, count in list_accessible_tags_with_counts(db, user)
            ],
        )

    @server.tool(
        name="tags.add_to_item", description="Add a Tag to an editable Item.", annotations=WRITE
    )
    def tags_add_to_item(item_id: str, name: str) -> WriteResult:
        assignment = runtime.call(
            "tags.add_to_item",
            lambda db, user: add_tag_to_item(db, user, item_id, name),
            conceal_resource="item not found",
        )
        return WriteResult(id=assignment.tag_id)

    @server.tool(
        name="tags.remove_from_item",
        description="Remove a Tag from an editable Item.",
        annotations=DESTRUCTIVE,
    )
    def tags_remove_from_item(item_id: str, tag_id: str) -> dict[str, bool]:
        runtime.call(
            "tags.remove_from_item",
            lambda db, user: remove_tag_from_item(db, user, item_id, tag_id),
            conceal_resource="item not found",
        )
        return {"ok": True}

    @server.tool(
        name="tags.set_for_item",
        description="Replace all Tags for an editable Item.",
        annotations=DESTRUCTIVE,
    )
    def tags_set_for_item(
        item_id: str, tag_ids: list[str], new_names: list[str] | None = None
    ) -> dict[str, bool]:
        runtime.call(
            "tags.set_for_item",
            lambda db, user: set_item_tags(db, user, item_id, tag_ids, new_names),
            conceal_resource="item not found",
        )
        return {"ok": True}

    @server.tool(
        name="discussions.list",
        description="List Discussion Messages for a visible Item.",
        annotations=READ_ONLY,
    )
    def discussions_list(item_id: str) -> list[DiscussionMessageView]:
        def run(db, user):
            workspace = open_item_workspace(db, user, item_id, WorkspaceSection.discussion)
            if not isinstance(workspace, DiscussionWorkspace):  # pragma: no cover
                return []
            return discussion_message_views(workspace)

        return runtime.call("discussions.list", run, conceal_resource="item not found")

    @server.tool(
        name="discussions.add",
        description="Add a Discussion Message to a visible Item.",
        annotations=WRITE,
    )
    def discussions_add(item_id: str, body: str) -> WriteResult:
        message = runtime.call(
            "discussions.add",
            lambda db, user: add_discussion_message(db, user, item_id, body),
            conceal_resource="item not found",
        )
        return WriteResult(id=message.id)

    @server.tool(
        name="discussions.delete",
        description="Delete the User's own Discussion Message.",
        annotations=DESTRUCTIVE,
    )
    def discussions_delete(item_id: str, message_id: str) -> dict[str, bool]:
        runtime.call(
            "discussions.delete",
            lambda db, user: delete_discussion_message(db, user, item_id, message_id),
            conceal_resource="discussion message not found",
        )
        return {"ok": True}
