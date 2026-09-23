from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from quirebase.web.api.library_schemas import ItemSearchView, item_search_view


class ProjectSummaryView(BaseModel):
    id: str
    name: str
    role: str
    item_count: int
    state: str
    visibility: str
    description: str = ""
    sharing_mode: str = "live"


class ProjectMemberView(BaseModel):
    user_id: str
    username: str
    role: str


class ProjectDetailView(ProjectSummaryView):
    members: list[ProjectMemberView]
    items: list[ItemSearchView]


class JoinableProjectView(BaseModel):
    id: str
    name: str
    item_count: int
    state: str
    visibility: str
    description: str = ""
    sharing_mode: str = "live"


def project_detail_view(workspace: Any) -> ProjectDetailView:
    return ProjectDetailView(
        id=workspace.project.id,
        name=workspace.project.name,
        role=workspace.membership.role,
        item_count=len(workspace.items),
        state=workspace.project.state.value,
        visibility=workspace.project.visibility.value,
        description=workspace.project.description,
        sharing_mode=workspace.project.sharing_mode.value,
        members=[
            ProjectMemberView(
                user_id=member.user.id,
                username=member.user.username,
                role=member.role,
            )
            for member in workspace.members
        ],
        items=[item_search_view(item) for item in workspace.items],
    )


class ProjectCreateRequest(BaseModel):
    name: str = Field(max_length=240)
    visibility: Literal["private", "public"] = "private"
    description: str = Field(default="", max_length=2000)
    sharing_mode: Literal["live", "independent"] = "live"


class ProjectSettingsRequest(BaseModel):
    name: str = Field(max_length=240)
    visibility: Literal["private", "public"]
    description: str = Field(max_length=2000)
    sharing_mode: Literal["live", "independent"]


class ProjectVisibilityRequest(BaseModel):
    visibility: Literal["private", "public"]


class ProjectSharingModeRequest(BaseModel):
    sharing_mode: Literal["live", "independent"]


class ProjectDescriptionRequest(BaseModel):
    description: str = Field(max_length=2000)


class ProjectDeleteRequest(BaseModel):
    confirmation: str


class ProjectMemberRequest(BaseModel):
    username: str
    role: Literal["admin", "editor", "viewer"] = "viewer"
