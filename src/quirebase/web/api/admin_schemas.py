from __future__ import annotations

from datetime import datetime  # ruff: ignore[typing-only-standard-library-import] - Pydantic resolves it
from typing import Any, Literal

from pydantic import BaseModel, Field


class AdminUserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12)
    role: Literal["member", "administrator"] = "member"


class UserStatusRequest(BaseModel):
    active: bool


class BreakGlassReadRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


class AdminWorkspaceView(BaseModel):
    id: str
    name: str
    owner_id: str
    state: str
    governance_suspended_at: datetime | None = None
    governance_suspended_by: str | None = None


class UserRoleRequest(BaseModel):
    role: Literal["member", "administrator"]


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=12)


class InvitationCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    role: Literal["member", "administrator"] = "member"


class RuntimeSettingsRequest(BaseModel):
    registration_policy: Literal["open", "closed", "invitation_only"] = "invitation_only"
    workspace_creation_policy: Literal["admins_only", "members_allowed"] = "admins_only"
    metadata_contact_email: str = ""
    ncbi_api_key: str = ""
    openalex_api_key: str = ""
    nasa_ads_token: str = ""
    ieee_api_key: str = ""
    session_days: int = Field(default=30, ge=1)
    max_pdf_bytes: int = Field(default=262_144_000, ge=1)
    max_attachment_bytes: int = Field(default=262_144_000, ge=1)
    export_ttl_hours: int = Field(default=24, ge=1)


class AdminUserView(BaseModel):
    id: str
    username: str
    role: str
    active: bool
    created_at: datetime


class AdminInvitationView(BaseModel):
    id: str
    username: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None = None


class AdminUsersView(BaseModel):
    users: list[AdminUserView]
    total: int
    page: int
    per_page: int
    invitations: list[AdminInvitationView]


class AdminInvitationCreatedView(BaseModel):
    id: str
    username: str
    role: str
    expires_at: datetime
    token: str
    accept_path: str


class StorageMetricsView(BaseModel):
    items_count: int
    revisions_count: int
    attachments_count: int
    thumbnails_count: int
    revisions_bytes: int
    attachments_bytes: int
    thumbnails_bytes: int
    total_disk_bytes: int
    missing_files_count: int
    integrity_status: str
    integrity_checked_at: datetime | None = None


class AdminAuditEventView(BaseModel):
    id: str
    actor_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    action: str
    target_type: str
    target_id: str | None = None
    target_ids: list[str] | None = None
    authorization_role: str | None = None
    authorization_capability: str | None = None
    result: str | None = None
    source: str | None = None
    detail: Any | None = None
    created_at: datetime


class WorkflowSummaryView(BaseModel):
    id: str
    name: str
    state: str
    raw_status: str
    queue_name: str | None = None
    executor_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    output: Any | None = None
    error: str | None = None
    attributes: dict[str, Any] | None = None
    authenticated_user: str | None = None


class AdminOverviewView(BaseModel):
    user_count: int
    pending_invitation_count: int
    failed_workflows: list[WorkflowSummaryView]
    storage: StorageMetricsView
    recent_events: list[AdminAuditEventView]


class AdminAuditView(BaseModel):
    events: list[AdminAuditEventView]
    total: int
    page: int
    per_page: int


class AdminWorkflowsView(BaseModel):
    workflows: list[WorkflowSummaryView]


class AdminSettingsView(BaseModel):
    registration_policy: Literal["open", "closed", "invitation_only"]
    workspace_creation_policy: Literal["admins_only", "members_allowed"]
    metadata_contact_email: str
    ncbi_api_key: str
    openalex_api_key: str
    nasa_ads_token: str
    ieee_api_key: str
    session_days: int
    max_pdf_bytes: int
    max_attachment_bytes: int
    export_ttl_hours: int
    database_url: str
    data_dir: str


class AdminMaintenanceView(BaseModel):
    storage: StorageMetricsView
    workflows: list[WorkflowSummaryView]
