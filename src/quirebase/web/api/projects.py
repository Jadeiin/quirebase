from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, status

from quirebase.access import (
    ResourceAction,
    project_decisions,
    project_participation_changes,
    require_workspace_action,
)
from quirebase.library import (
    add_project_discussion_message,
    delete_project_discussion_message,
    list_project_discussion_messages,
    moderate_project_discussion_message,
)
from quirebase.models import ProjectState
from quirebase.projects import (
    add_item_to_project,
    add_project_member,
    create_project,
    delete_project,
    join_project,
    leave_project,
    list_workspace_projects,
    open_project_workspace,
    remove_item_from_project,
    require_project,
    set_project_state,
    update_project_settings,
)
from quirebase.projects import (
    remove_project_member as remove_project_member_domain,
)
from quirebase.web.api.common import OkView, WriteResult, authorization_view
from quirebase.web.api.dependencies import ApiUser, Database, WorkspaceAccess
from quirebase.web.api.library_schemas import (
    DiscussionMessageView,
    DiscussionModerationRequest,
    DiscussionRequest,
    discussion_message_view,
)
from quirebase.web.api.project_schemas import (
    ProjectCreateRequest,
    ProjectDeleteRequest,
    ProjectDetailView,
    ProjectMemberRequest,
    ProjectMemberView,
    ProjectSettingsRequest,
    ProjectSummaryView,
    project_detail_view,
)

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("", response_model=list[ProjectSummaryView])
async def list_projects(
    workspace_id: str,
    context: WorkspaceAccess,
    db: Database,
    view: Literal["mine", "joinable", "all"] = "all",
):
    return [
        ProjectSummaryView(
            id=project.id,
            name=project.name,
            item_count=count,
            state=project.state,
            participation=project.participation,
            description=project.description,
            is_participating=is_participating,
            allowed_participation_changes=list(project_participation_changes(context, project)),
            authorization=authorization_view(
                project_decisions(context, project, is_participating=is_participating)
            ),
        )
        for project, count, is_participating in await list_workspace_projects(
            db, context, view=view
        )
    ]


@router.post("", response_model=WriteResult, status_code=status.HTTP_201_CREATED)
async def create_user_project(
    workspace_id: str, data: ProjectCreateRequest, user: ApiUser, db: Database
) -> WriteResult:
    project = await create_project(
        db, user, workspace_id, data.name, data.participation, data.description
    )
    return WriteResult(id=project.id)


@router.get("/{project_id}", response_model=ProjectDetailView)
async def get_project(
    workspace_id: str, project_id: str, context: WorkspaceAccess, db: Database
) -> ProjectDetailView:
    workspace = await open_project_workspace(db, context, project_id)
    return project_detail_view(
        workspace,
        allowed_participation_changes=list(
            project_participation_changes(context, workspace.project)
        ),
        authorization=authorization_view(
            project_decisions(
                context,
                workspace.project,
                is_participating=workspace.is_participating,
            )
        ),
    )


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
        participation=data.participation,
    )
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


@router.post("/{project_id}/join", response_model=ProjectMemberView)
async def join_project_api(
    workspace_id: str, project_id: str, user: ApiUser, db: Database
) -> ProjectMemberView:
    await join_project(db, user, workspace_id, project_id)
    return ProjectMemberView(user_id=user.id, username=user.username)


@router.post("/{project_id}/leave", response_model=OkView)
async def leave_project_api(
    workspace_id: str, project_id: str, user: ApiUser, db: Database
) -> OkView:
    await leave_project(db, user, workspace_id, project_id)
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
    return ProjectMemberView(user_id=member.user_id, username=member.username)


@router.delete("/{project_id}/members/{user_id}", response_model=OkView)
async def remove_project_member(
    workspace_id: str, project_id: str, user_id: str, user: ApiUser, db: Database
) -> OkView:
    await remove_project_member_domain(db, user, workspace_id, project_id, user_id)
    return OkView()


@router.get("/{project_id}/discussions", response_model=list[DiscussionMessageView])
async def list_project_discussions(
    workspace_id: str, project_id: str, context: WorkspaceAccess, db: Database
) -> list[DiscussionMessageView]:
    project_context = await require_project(db, context, project_id)
    messages = await list_project_discussion_messages(db, project_context)
    project = project_context.project
    return [
        discussion_message_view(message, context, writable=project.state is ProjectState.active)
        for message in messages
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
    message = await add_project_discussion_message(db, user, workspace_id, project_id, data.body)
    context = await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    return discussion_message_view(message, context)


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


@router.post("/{project_id}/discussions/{message_id}/moderation", response_model=OkView)
async def moderate_project_discussion(
    workspace_id: str,
    project_id: str,
    message_id: str,
    data: DiscussionModerationRequest,
    user: ApiUser,
    db: Database,
) -> OkView:
    await moderate_project_discussion_message(
        db, user, workspace_id, project_id, message_id, data.reason
    )
    return OkView()
