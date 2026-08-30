from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcp.server.mcpserver.exceptions import ToolError

if TYPE_CHECKING:
    from collections.abc import Collection

TOOL_ALLOWLIST = frozenset({
    "annotations.create",
    "annotations.delete",
    "annotations.list",
    "annotations.update",
    "citations.format_item",
    "discovery.search",
    "discussions.add",
    "discussions.delete",
    "discussions.list",
    "documents.list",
    "library.create_item",
    "library.get_item",
    "library.search",
    "library.update_item",
    "projects.add_item",
    "projects.create",
    "projects.get",
    "projects.list",
    "projects.remove_item",
    "projects.remove_member",
    "projects.set_member",
    "tags.add_to_item",
    "tags.list",
    "tags.remove_from_item",
    "tags.set_for_item",
})


@dataclass(frozen=True)
class ToolPolicy:
    allowed_tools: Collection[str] = TOOL_ALLOWLIST

    def visible_tools(self) -> frozenset[str]:
        return frozenset(self.allowed_tools)

    def require(self, tool_name: str) -> None:
        if tool_name not in self.allowed_tools:
            raise ToolError("unknown tool")
