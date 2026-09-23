from __future__ import annotations

from fastapi import APIRouter, status

from quirebase.library import (
    add_project_discussion_message,
    delete_project_discussion_message,
    list_project_discussion_messages,
)
from quirebase.models import ProjectState
from quirebase.projects import (
    add_item_to_project,
    add_project_member,
    create_project,
    delete_project,
    list_user_projects,
    open_project_workspace,
    remove_item_from_project,
    set_project_state,
    set_project_visibility,
    update_project_description,
    update_project_settings,
)
from quirebase.projects import (
    remove_project_member as remove_project_member_domain,
)
from quirebase.web.api.common import OkView, WriteResult
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.library_schemas import (
    DiscussionMessageView,
    DiscussionRequest,
    discussion_message_view,
)
from quirebase.web.api.project_schemas import (
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

router = APIRouter(prefix="/workspaces/{workspace_id}/projects", tags=["Projects"])


@router.get("", response_model=list[ProjectSummaryView])
async def list_projects(workspace_id: str, user: ApiUser, db: Database):
    return [
        ProjectSummaryView(
            id=project.id,
            name=project.name,
            item_count=count,
            state=project.state.value,
            visibility=project.visibility.value,
            description=project.description,
        )
        for project, count in await list_user_projects(db, user, workspace_id)
    ]


@router.post("", response_model=WriteResult, status_code=status.HTTP_201_CREATED)
async def create_user_project(
    workspace_id: str, data: ProjectCreateRequest, user: ApiUser, db: Database
) -> WriteResult:
    project = await create_project(
        db, user, workspace_id, data.name, data.visibility, data.description
    )
    return WriteResult(id=project.id)


@router.get("/{project_id}", response_model=ProjectDetailView)
async def get_project(
    workspace_id: str, project_id: str, user: ApiUser, db: Database
) -> ProjectDetailView:
    return project_detail_view(await open_project_workspace(db, user, workspace_id, project_id))


@router.patch("/{project_id}", response_model=WriteResult)
async def update_project(
    workspace_id: str,
    project_id: str,
    data: ProjectSettingsRequest,
    user: ApiUser,
    db: Database,
) -> WriteResult:
    project = await update_project_settings(
        db,
        user,
        workspace_id,
        project_id,
        name=data.name,
        description=data.description,
        visibility=data.visibility,
    )
    return WriteResult(id=project.id)


@router.post("/{project_id}/description", response_model=WriteResult)
async def update_project_description_api(
    workspace_id: str,
    project_id: str,
    data: ProjectDescriptionRequest,
    user: ApiUser,
    db: Database,
) -> WriteResult:
    project = await update_project_description(db, user, workspace_id, project_id, data.description)
    return WriteResult(id=project.id)


@router.delete("/{project_id}", response_model=OkView)
async def delete_user_project(
    workspace_id: str,
    project_id: str,
    data: ProjectDeleteRequest,
    user: ApiUser,
    db: Database,
) -> OkView:
    await delete_project(db, user, workspace_id, project_id, data.confirmation)
    return OkView()


@router.post("/{project_id}/archive", response_model=OkView)
async def archive_project(
    workspace_id: str, project_id: str, user: ApiUser, db: Database
) -> OkView:
    await set_project_state(db, user, workspace_id, project_id, ProjectState.archived)
    return OkView()


@router.post("/{project_id}/restore", response_model=OkView)
async def restore_project(
    workspace_id: str, project_id: str, user: ApiUser, db: Database
) -> OkView:
    await set_project_state(db, user, workspace_id, project_id, ProjectState.active)
    return OkView()


@router.post("/{project_id}/visibility", response_model=OkView)
async def set_project_visibility_api(
    workspace_id: str,
    project_id: str,
    data: ProjectVisibilityRequest,
    user: ApiUser,
    db: Database,
) -> OkView:
    await set_project_visibility(db, user, workspace_id, project_id, data.visibility)
    return OkView()


@router.put("/{project_id}/items/{item_id}", response_model=OkView)
async def add_project_item(
    workspace_id: str, project_id: str, item_id: str, user: ApiUser, db: Database
) -> OkView:
    await add_item_to_project(db, user, workspace_id, project_id, item_id)
    return OkView()


@router.delete("/{project_id}/items/{item_id}", response_model=OkView)
async def remove_project_item(
    workspace_id: str, project_id: str, item_id: str, user: ApiUser, db: Database
) -> OkView:
    await remove_item_from_project(db, user, workspace_id, project_id, item_id)
    return OkView()


@router.put("/{project_id}/members", response_model=ProjectMemberView)
async def set_project_member(
    workspace_id: str,
    project_id: str,
    data: ProjectMemberRequest,
    user: ApiUser,
    db: Database,
) -> ProjectMemberView:
    member = await add_project_member(db, user, workspace_id, project_id, data.username)
    workspace = await open_project_workspace(db, user, workspace_id, project_id)
    matched = next(row for row in workspace.members if row.user.id == member.user_id)
    return ProjectMemberView(user_id=matched.user.id, username=matched.user.username)


@router.delete("/{project_id}/members/{user_id}", response_model=OkView)
async def remove_project_member(
    workspace_id: str, project_id: str, user_id: str, user: ApiUser, db: Database
) -> OkView:
    await remove_project_member_domain(db, user, workspace_id, project_id, user_id)
    return OkView()


@router.get("/{project_id}/discussions", response_model=list[DiscussionMessageView])
async def list_project_discussions(
    workspace_id: str, project_id: str, user: ApiUser, db: Database
) -> list[DiscussionMessageView]:
    return [
        discussion_message_view(message)
        for message in await list_project_discussion_messages(db, user, workspace_id, project_id)
    ]


@router.post(
    "/{project_id}/discussions",
    response_model=DiscussionMessageView,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_discussion(
    workspace_id: str,
    project_id: str,
    data: DiscussionRequest,
    user: ApiUser,
    db: Database,
) -> DiscussionMessageView:
    return discussion_message_view(
        await add_project_discussion_message(db, user, workspace_id, project_id, data.body)
    )


@router.delete("/{project_id}/discussions/{message_id}", response_model=OkView)
async def delete_project_discussion(
    workspace_id: str,
    project_id: str,
    message_id: str,
    user: ApiUser,
    db: Database,
) -> OkView:
    await delete_project_discussion_message(db, user, workspace_id, project_id, message_id)
    return OkView()
