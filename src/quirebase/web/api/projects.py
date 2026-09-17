from __future__ import annotations

from fastapi import APIRouter, status

from quirebase.models import ProjectState
from quirebase.projects import (
    add_item_to_project,
    add_project_member,
    create_project,
    delete_project,
    join_project,
    leave_project,
    list_joinable_projects,
    list_user_projects,
    open_project_workspace,
    remove_item_from_project,
    remove_project_member,
    set_project_state,
    set_project_visibility,
    transfer_project_ownership,
    update_project_description,
    update_project_settings,
)
from quirebase.web.api.common import OkView, WriteResult
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.project_schemas import (
    JoinableProjectView,
    ProjectCreateRequest,
    ProjectDeleteRequest,
    ProjectDescriptionRequest,
    ProjectDetailView,
    ProjectMemberRequest,
    ProjectMemberView,
    ProjectSettingsRequest,
    ProjectSummaryView,
    ProjectVisibilityRequest,
    project_detail_view,
)

router = APIRouter(prefix="/api/v1", tags=["Projects"])


@router.get("/projects", response_model=list[ProjectSummaryView], operation_id="projects.list")
async def list_projects(user: ApiUser, db: Database) -> list[ProjectSummaryView]:
    rows = await list_user_projects(db, user)
    return [
        ProjectSummaryView(
            id=project.id,
            name=project.name,
            role=role,
            item_count=count,
            state=project.state.value,
            visibility=project.visibility.value,
            description=project.description,
        )
        for project, role, count in rows
    ]


@router.get("/projects/joinable", response_model=list[JoinableProjectView])
async def list_projects_available_to_join(user: ApiUser, db: Database):
    rows = await list_joinable_projects(db, user)
    return [
        {
            "id": project.id,
            "name": project.name,
            "item_count": count,
            "state": project.state.value,
            "visibility": project.visibility.value,
            "description": project.description,
        }
        for project, count in rows
    ]


@router.post(
    "/projects",
    response_model=WriteResult,
    status_code=status.HTTP_201_CREATED,
    operation_id="projects.create",
)
async def create_user_project(
    data: ProjectCreateRequest, user: ApiUser, db: Database
) -> WriteResult:
    project = await create_project(db, user, data.name, data.visibility, data.description)
    return WriteResult(id=project.id)


@router.get("/projects/{project_id}", response_model=ProjectDetailView, operation_id="projects.get")
async def get_project(project_id: str, user: ApiUser, db: Database) -> ProjectDetailView:
    return project_detail_view(await open_project_workspace(db, user, project_id))


@router.patch(
    "/projects/{project_id}",
    response_model=WriteResult,
    operation_id="projects.update_settings",
)
async def update_project(
    project_id: str, data: ProjectSettingsRequest, user: ApiUser, db: Database
) -> WriteResult:
    project = await update_project_settings(
        db,
        user,
        project_id,
        name=data.name,
        description=data.description,
        visibility=data.visibility,
    )
    return WriteResult(id=project.id)


@router.post("/projects/{project_id}/description", response_model=WriteResult)
async def update_project_description_api(
    project_id: str, data: ProjectDescriptionRequest, user: ApiUser, db: Database
) -> WriteResult:
    project = await update_project_description(db, user, project_id, data.description)
    return WriteResult(id=project.id)


@router.delete("/projects/{project_id}", response_model=OkView, operation_id="projects.delete")
async def delete_user_project(
    project_id: str, data: ProjectDeleteRequest, user: ApiUser, db: Database
) -> OkView:
    await delete_project(db, user, project_id, data.confirmation)
    return OkView()


@router.post(
    "/projects/{project_id}/archive", response_model=OkView, operation_id="projects.archive"
)
async def archive_project(project_id: str, user: ApiUser, db: Database) -> OkView:
    await set_project_state(db, user, project_id, ProjectState.archived)
    return OkView()


@router.post(
    "/projects/{project_id}/restore", response_model=OkView, operation_id="projects.restore"
)
async def restore_project(project_id: str, user: ApiUser, db: Database) -> OkView:
    await set_project_state(db, user, project_id, ProjectState.active)
    return OkView()


@router.post("/projects/{project_id}/visibility", response_model=OkView)
async def set_project_visibility_api(
    project_id: str, data: ProjectVisibilityRequest, user: ApiUser, db: Database
) -> OkView:
    await set_project_visibility(db, user, project_id, data.visibility)
    return OkView()


@router.post("/projects/{project_id}/leave", response_model=OkView, operation_id="projects.leave")
async def leave_user_project(project_id: str, user: ApiUser, db: Database) -> OkView:
    await leave_project(db, user, project_id)
    return OkView()


@router.post("/projects/{project_id}/join", response_model=OkView)
async def join_public_project(project_id: str, user: ApiUser, db: Database) -> OkView:
    await join_project(db, user, project_id)
    return OkView()


@router.post(
    "/projects/{project_id}/ownership/{user_id}",
    response_model=OkView,
    operation_id="projects.transfer_ownership",
)
async def transfer_user_project(
    project_id: str, user_id: str, user: ApiUser, db: Database
) -> OkView:
    await transfer_project_ownership(db, user, project_id, user_id)
    return OkView()


@router.put(
    "/projects/{project_id}/items/{item_id}",
    response_model=OkView,
    operation_id="projects.add_item",
)
async def add_project_item(project_id: str, item_id: str, user: ApiUser, db: Database) -> OkView:
    await add_item_to_project(db, user, project_id, item_id)
    return OkView()


@router.delete(
    "/projects/{project_id}/items/{item_id}",
    response_model=OkView,
    operation_id="projects.remove_item",
)
async def remove_project_item(project_id: str, item_id: str, user: ApiUser, db: Database) -> OkView:
    await remove_item_from_project(db, user, project_id, item_id)
    return OkView()


@router.put(
    "/projects/{project_id}/members",
    response_model=ProjectMemberView,
    operation_id="projects.set_member",
)
async def set_project_member(
    project_id: str, data: ProjectMemberRequest, user: ApiUser, db: Database
) -> ProjectMemberView:
    member = await add_project_member(db, user, project_id, data.username, data.role)
    workspace = await open_project_workspace(db, user, project_id)
    matched = next(row for row in workspace.members if row.user.id == member.user_id)
    return ProjectMemberView(
        user_id=matched.user.id,
        username=matched.user.username,
        role=matched.role,
    )


@router.delete(
    "/projects/{project_id}/members/{user_id}",
    response_model=OkView,
    operation_id="projects.remove_member",
)
async def delete_project_member(
    project_id: str, user_id: str, user: ApiUser, db: Database
) -> OkView:
    await remove_project_member(db, user, project_id, user_id)
    return OkView()
