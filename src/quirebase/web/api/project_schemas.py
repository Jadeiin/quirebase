from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from pydantic.json_schema import SkipJsonSchema  # ruff: ignore[typing-only-third-party-import] — Pydantic resolves field annotations.

from quirebase.models import ProjectParticipation, ProjectState
from quirebase.projects import ProjectParticipantInfo, ProjectWorkspace
from quirebase.web.api.common import WorkspaceAuthorizationView


class ProjectSummaryView(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    item_count: int
    state: ProjectState
    participation: ProjectParticipation
    is_participating: bool
    description: str = ""
    allowed_participation_changes: list[ProjectParticipation]
    authorization: WorkspaceAuthorizationView


class ProjectDetailView(ProjectSummaryView):
    active_participants: list[ProjectParticipantInfo] = Field(
        description="Active explicit participants; Workspace participation is implicit."
    )


def project_detail_view(
    workspace: ProjectWorkspace,
    *,
    authorization: WorkspaceAuthorizationView,
    allowed_participation_changes: list[ProjectParticipation],
) -> ProjectDetailView:
    return ProjectDetailView(
        id=workspace.project.id,
        name=workspace.project.name,
        created_at=workspace.project.created_at,
        updated_at=workspace.project.updated_at,
        item_count=workspace.item_count,
        state=workspace.project.state,
        participation=workspace.project.participation,
        is_participating=workspace.is_participating,
        description=workspace.project.description,
        authorization=authorization,
        allowed_participation_changes=allowed_participation_changes,
        active_participants=list(workspace.active_participants),
    )


class ProjectCreateRequest(BaseModel):
    name: str = Field(max_length=240)
    participation: ProjectParticipation
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


class ProjectParticipantRequest(BaseModel):
    username: str
