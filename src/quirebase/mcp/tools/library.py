from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from quirebase.library import (
    ItemMetadata,
    MetadataWorkspace,
    WorkspaceSection,
    create_item,
    get_item_citation_text_response,
    open_item_workspace,
    revise_item_metadata,
    search_library,
)
from quirebase.mcp.tools.annotations import READ_ONLY, WRITE
from quirebase.programmatic import (
    CitationView,
    ItemDetailView,
    LibrarySearchView,
    WriteResult,
    item_detail_view,
    item_search_view,
)

if TYPE_CHECKING:
    from mcp.server import MCPServer

    from quirebase.mcp.runtime import McpRuntime


def register_library_tools(server: MCPServer, runtime: McpRuntime) -> None:
    @server.tool(
        name="library.search",
        description="Search bibliographic Items visible to the authenticated User.",
        annotations=READ_ONLY,
    )
    async def library_search(
        query: str = "",
        tag: str = "",
        project: str = "",
        year: str = "",
        keyword: str = "",
        author: str = "",
        page: Annotated[int, Field(ge=1)] = 1,
    ) -> LibrarySearchView:
        per_page = 25

        async def run(db, user):
            items, total, _tags, _years = await search_library(
                db,
                user,
                q=query,
                tag=tag,
                project=project,
                year=year,
                keyword=keyword,
                author=author,
                page=page,
                per_page=per_page,
            )
            return LibrarySearchView(
                items=[item_search_view(item) for item in items],
                total=total,
                page=page,
                per_page=per_page,
            )

        return await runtime.call("library.search", run)

    @server.tool(
        name="library.get_item",
        description="Get bibliographic metadata for one visible Item; never returns file content.",
        annotations=READ_ONLY,
    )
    async def library_get_item(item_id: str) -> ItemDetailView:
        async def run(db, user):
            workspace = await open_item_workspace(db, user, item_id, WorkspaceSection.metadata)
            if not isinstance(workspace, MetadataWorkspace):  # pragma: no cover
                raise ToolError("item metadata unavailable")
            return item_detail_view(workspace)

        return await runtime.call("library.get_item", run, conceal_resource="item not found")

    @server.tool(
        name="library.create_item",
        description="Create a bibliographic Item owned by the authenticated User.",
        annotations=WRITE,
    )
    async def library_create_item(metadata: ItemMetadata) -> WriteResult:
        result = await runtime.call(
            "library.create_item", lambda db, user: create_item(db, user, metadata)
        )
        return WriteResult(id=result.item_id, version=result.version)

    @server.tool(
        name="library.update_item",
        description="Replace editable Item metadata using optimistic version checking.",
        annotations=WRITE,
    )
    async def library_update_item(
        item_id: str, expected_version: Annotated[int, Field(ge=1)], metadata: ItemMetadata
    ) -> WriteResult:
        result = await runtime.call(
            "library.update_item",
            lambda db, user: revise_item_metadata(db, user, item_id, expected_version, metadata),
            conceal_resource="item not found",
        )
        return WriteResult(id=result.item_id, version=result.version)

    @server.tool(
        name="citations.format_item",
        description="Render a visible Item as a plain-text or HTML citation.",
        annotations=READ_ONLY,
    )
    async def citations_format_item(
        item_id: str,
        style_key: str = "apa",
        output: Annotated[str, Field(pattern="^(text|html)$")] = "text",
    ) -> CitationView:
        content, media_type = await runtime.call(
            "citations.format_item",
            lambda db, user: get_item_citation_text_response(
                db, user, item_id, style_key=style_key, output=output
            ),
            conceal_resource="item not found",
        )
        return CitationView(content=content, media_type=media_type)
