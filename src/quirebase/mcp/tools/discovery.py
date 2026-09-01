from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from quirebase.library import CandidatePageView, DiscoveryClause, search_candidate_records
from quirebase.mcp.tools.annotations import OPEN_WORLD_READ

if TYPE_CHECKING:
    from mcp.server import MCPServer

    from quirebase.core.config import Settings
    from quirebase.mcp.runtime import McpRuntime


def register_discovery_tools(server: MCPServer, runtime: McpRuntime, settings: Settings) -> None:
    @server.tool(
        name="discovery.search",
        description="Search an external scholarly metadata Provider; never forwards the API Token.",
        annotations=OPEN_WORLD_READ,
    )
    async def discovery_search(
        provider: str,
        clauses: list[DiscoveryClause],
        page: Annotated[int, Field(ge=1)] = 1,
        per_page: Annotated[int, Field(ge=1, le=100)] = 10,
        sort: str = "relevance",
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> CandidatePageView:
        async def run(db, user):
            return await search_candidate_records(
                db,
                user,
                provider,
                tuple(clauses),
                page=page,
                per_page=per_page,
                sort=sort,
                year_from=year_from,
                year_to=year_to,
                settings=settings,
            )

        return await runtime.call(
            "discovery.search",
            run,
        )
