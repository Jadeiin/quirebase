from __future__ import annotations

from typing import TYPE_CHECKING

from quirebase.mcp.tools.annotations import DESTRUCTIVE, READ_ONLY, WRITE
from quirebase.programmatic import (
    ProjectDetailView,
    ProjectMemberView,
    ProjectSummaryView,
    WriteResult,
    project_detail_view,
)
from quirebase.projects import (
    add_item_to_project,
    add_project_member,
    create_project,
    list_user_projects,
    open_project_workspace,
    remove_item_from_project,
    remove_project_member,
)

if TYPE_CHECKING:
    from mcp.server import MCPServer

    from quirebase.mcp.runtime import McpRuntime


def register_project_tools(server: MCPServer, runtime: McpRuntime) -> None:
    @server.tool(
        name="projects.list",
        description="List Projects joined by the authenticated User.",
        annotations=READ_ONLY,
    )
    async def projects_list() -> list[ProjectSummaryView]:
        async def run(db, user):
            rows = await list_user_projects(db, user)
            return [
                ProjectSummaryView(id=project.id, name=project.name, role=role, item_count=count)
                for project, role, count in rows
            ]

        return await runtime.call(
            "projects.list",
            run,
        )

    @server.tool(
        name="projects.get",
        description="Get one joined Project, its members, and bibliographic Items.",
        annotations=READ_ONLY,
    )
    async def projects_get(project_id: str) -> ProjectDetailView:
        async def run(db, user):
            workspace = await open_project_workspace(db, user, project_id)
            return project_detail_view(workspace)

        return await runtime.call("projects.get", run, conceal_resource="project not found")

    @server.tool(
        name="projects.create",
        description="Create a Project owned by the authenticated User.",
        annotations=WRITE,
    )
    async def projects_create(name: str) -> WriteResult:
        async def run(db, user):
            return await create_project(db, user, name)

        project = await runtime.call("projects.create", run)
        return WriteResult(id=project.id)

    @server.tool(
        name="projects.add_item",
        description="Add a visible Item to a Project where the User may edit membership content.",
        annotations=WRITE,
    )
    async def projects_add_item(project_id: str, item_id: str) -> dict[str, bool]:
        async def run(db, user):
            await add_item_to_project(db, user, project_id, item_id)

        await runtime.call(
            "projects.add_item",
            run,
            conceal_resource="project or item not found",
        )
        return {"ok": True}

    @server.tool(
        name="projects.remove_item",
        description="Remove an Item from a Project where the User may edit membership content.",
        annotations=DESTRUCTIVE,
    )
    async def projects_remove_item(project_id: str, item_id: str) -> dict[str, bool]:
        async def run(db, user):
            await remove_item_from_project(db, user, project_id, item_id)

        await runtime.call(
            "projects.remove_item",
            run,
            conceal_resource="project or item not found",
        )
        return {"ok": True}

    @server.tool(
        name="projects.set_member",
        description="Add or change a Project member; requires the Project owner role.",
        annotations=WRITE,
    )
    async def projects_set_member(
        project_id: str, username: str, role: str = "viewer"
    ) -> ProjectMemberView:
        async def run(db, user):
            member = await add_project_member(db, user, project_id, username, role)
            workspace = await open_project_workspace(db, user, project_id)
            matched = next(row for row in workspace.members if row.user.id == member.user_id)
            return ProjectMemberView(
                user_id=matched.user.id,
                username=matched.user.username,
                role=matched.role,
            )

        return await runtime.call(
            "projects.set_member",
            run,
            conceal_resource="project or user not found",
        )

    @server.tool(
        name="projects.remove_member",
        description="Remove a Project member; requires the Project owner role.",
        annotations=DESTRUCTIVE,
    )
    async def projects_remove_member(project_id: str, user_id: str) -> dict[str, bool]:
        async def run(db, user):
            await remove_project_member(db, user, project_id, user_id)

        await runtime.call(
            "projects.remove_member",
            run,
            conceal_resource="project or member not found",
        )
        return {"ok": True}
