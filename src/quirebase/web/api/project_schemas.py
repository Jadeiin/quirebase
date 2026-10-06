from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator
from pydantic.json_schema import SkipJsonSchema  # ruff: ignore[typing-only-third-party-import] — Pydantic resolves field annotations.

from quirebase.models import ProjectParticipation, ProjectState
from quirebase.web.api.common import WorkspaceAuthorizationView
from quirebase.web.api.library_schemas import ItemSearchView, item_search_view


class ProjectSummaryView(BaseModel):
    id: str
    name: str
    item_count: int
    state: ProjectState
    participation: ProjectParticipation
    is_member: bool
    description: str = ""
    allowed_participation_changes: list[ProjectParticipation]
    authorization: WorkspaceAuthorizationView


class ProjectMemberView(BaseModel):
    user_id: str
    username: str


class ProjectDetailView(ProjectSummaryView):
    members: list[ProjectMemberView]
    items: list[ItemSearchView]


def project_detail_view(
    workspace: Any,
    *,
    authorization: WorkspaceAuthorizationView,
    allowed_participation_changes: list[ProjectParticipation],
) -> ProjectDetailView:
    return ProjectDetailView(
        id=workspace.project.id,
        name=workspace.project.name,
        item_count=len(workspace.items),
        state=workspace.project.state,
        participation=workspace.project.participation,
        is_member=workspace.is_member,
        description=workspace.project.description,
        authorization=authorization,
        allowed_participation_changes=allowed_participation_changes,
        members=[
            ProjectMemberView(user_id=member.user.id, username=member.user.username)
            for member in workspace.members
        ],
        items=[item_search_view(item) for item in workspace.items],
    )


class ProjectCreateRequest(BaseModel):
    name: str = Field(max_length=240)
    participation: ProjectParticipation = ProjectParticipation.workspace
    description: str = Field(default="", max_length=2000)


class ProjectSettingsRequest(BaseModel):
    name: str | SkipJsonSchema[None] = Field(default=None, max_length=240)
    participation: ProjectParticipation | SkipJsonSchema[None] = None
    description: str | SkipJsonSchema[None] = Field(default=None, max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def require_changes(cls, value: Any) -> Any:
        if isinstance(value, dict):
            changes = {field: value[field] for field in cls.model_fields if field in value}
            if not changes or any(change is None for change in changes.values()):
                raise ValueError("Supply at least one Project setting; settings cannot be null")
        return value


class ProjectDeleteRequest(BaseModel):
    confirmation: str


class ProjectMemberRequest(BaseModel):
    username: str
