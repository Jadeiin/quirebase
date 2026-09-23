from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from quirebase.web.api.library_schemas import ItemSearchView, item_search_view


class ProjectSummaryView(BaseModel):
    id: str
    name: str
    item_count: int
    state: str
    visibility: str
    description: str = ""


class ProjectMemberView(BaseModel):
    user_id: str
    username: str


class ProjectDetailView(ProjectSummaryView):
    members: list[ProjectMemberView]
    items: list[ItemSearchView]


def project_detail_view(workspace: Any) -> ProjectDetailView:
    return ProjectDetailView(
        id=workspace.project.id,
        name=workspace.project.name,
        item_count=len(workspace.items),
        state=workspace.project.state.value,
        visibility=workspace.project.visibility.value,
        description=workspace.project.description,
        members=[
            ProjectMemberView(user_id=member.user.id, username=member.user.username)
            for member in workspace.members
        ],
        items=[item_search_view(item) for item in workspace.items],
    )


class ProjectCreateRequest(BaseModel):
    name: str = Field(max_length=240)
    visibility: Literal["workspace", "members"] = "workspace"
    description: str = Field(default="", max_length=2000)


class ProjectSettingsRequest(BaseModel):
    name: str = Field(max_length=240)
    visibility: Literal["workspace", "members"]
    description: str = Field(max_length=2000)


class ProjectVisibilityRequest(BaseModel):
    visibility: Literal["workspace", "members"]


class ProjectDescriptionRequest(BaseModel):
    description: str = Field(max_length=2000)


class ProjectDeleteRequest(BaseModel):
    confirmation: str


class ProjectMemberRequest(BaseModel):
    username: str
