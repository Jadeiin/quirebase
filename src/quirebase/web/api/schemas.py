from __future__ import annotations

from datetime import datetime  # ruff: ignore[typing-only-standard-library-import] - Pydantic resolves it
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from quirebase.library import DiscoveryClause, ItemMetadata
from quirebase.programmatic import ItemSearchView


class ItemUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    metadata: ItemMetadata


class NameRequest(BaseModel):
    name: str = Field(max_length=240)


class ProjectCreateRequest(BaseModel):
    name: str = Field(max_length=240)
    visibility: Literal["private", "public"] = "private"
    description: str = Field(default="", max_length=2000)


class ProjectSettingsRequest(BaseModel):
    name: str = Field(max_length=240)
    visibility: Literal["private", "public"]
    description: str = Field(max_length=2000)


class ProjectVisibilityRequest(BaseModel):
    visibility: Literal["private", "public"]


class ProjectDescriptionRequest(BaseModel):
    description: str = Field(max_length=2000)


class ProjectDeleteRequest(BaseModel):
    confirmation: str


class ProjectMemberRequest(BaseModel):
    username: str
    role: Literal["editor", "viewer"] = "viewer"


class TagSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Tag mutations are explicit intent deltas. A full collection replacement
    # would derive removals from a stale read and lose concurrent additions.
    add_tag_ids: list[str] = Field(default_factory=list)
    remove_tag_ids: list[str] = Field(default_factory=list)
    new_names: list[str] = Field(default_factory=list)


class DiscussionRequest(BaseModel):
    body: str


class DiscoverySearchRequest(BaseModel):
    provider: str
    clauses: list[DiscoveryClause]
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=10, ge=1, le=100)
    sort: str = "relevance"
    year_from: int | None = Field(default=None, ge=1000, le=9999)
    year_to: int | None = Field(default=None, ge=1000, le=9999)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1)


class InvitationAcceptRequest(BaseModel):
    password: str = Field(min_length=1)


class ApiTokenCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    days: int = Field(default=30, ge=1, le=365)


class ApiTokenView(BaseModel):
    id: str
    name: str
    status: Literal["active", "expired", "revoked"]
    expires_at: datetime
    created_at: datetime


class ApiTokenGrantView(BaseModel):
    id: str
    token: str
    expires_at: datetime


class LoginSessionView(BaseModel):
    id: str
    current: bool = False
    expires_at: datetime
    created_at: datetime


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class LocaleRequest(BaseModel):
    locale: str


class IdentifierImportRequest(BaseModel):
    identifier: str = Field(min_length=1)
    provider: str = "auto"


class BulkActionRequest(BaseModel):
    item_ids: list[str]
    action: str
    project_id: str = ""
    tag_name: str = ""
    confirmation: str = ""


class BibliographyExportRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list)
    file_format: str
    style: str = "apa"
    include_abstract: bool = True
    preserve_case: bool = False
    include_identifiers: bool = False
    include_custom_fields: bool = False
    encoding: str = "unicode"
    journal_mode: str = "full"
    doi_policy: str = "include"
    url_policy: str = "include"
    excluded_fields: list[str] = Field(default_factory=list)
    sort_by: str = "input"
    citation_key_formula: str = ""
    citation_key_force_ascii: bool = False


class DocumentArchiveRequest(BaseModel):
    item_ids: list[str]
    include_annotations: bool = False
    include_supplements: bool = False
    timezone: str = ""


class CitationStyleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    csl: str = Field(min_length=1)


class TagMergeRequest(BaseModel):
    source_tag_id: str
    target_tag_id: str


class DeleteConfirmationRequest(BaseModel):
    confirmation: str


class MetadataSyncRequest(BaseModel):
    expected_version: int = Field(ge=1)
    provider: str
    uid: str


class RemoteRevisionRequest(BaseModel):
    source: str = Field(min_length=1, max_length=4000)


class RemoteAttachmentRequest(RemoteRevisionRequest):
    graphical_abstract: bool = False


class AdminUserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12)
    role: Literal["member", "administrator"] = "member"


class UserStatusRequest(BaseModel):
    active: bool


class UserRoleRequest(BaseModel):
    role: Literal["member", "administrator"]


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=12)


class InvitationCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    role: Literal["member", "administrator"] = "member"


class RuntimeSettingsRequest(BaseModel):
    metadata_contact_email: str = ""
    ncbi_api_key: str = ""
    openalex_api_key: str = ""
    nasa_ads_token: str = ""
    ieee_api_key: str = ""
    session_days: int = Field(default=30, ge=1)
    max_pdf_bytes: int = Field(default=262_144_000, ge=1)
    max_attachment_bytes: int = Field(default=262_144_000, ge=1)
    export_ttl_hours: int = Field(default=24, ge=1)


class SessionUserView(BaseModel):
    id: str
    username: str
    role: Literal["administrator", "member"]


class SessionView(BaseModel):
    authenticated: bool
    user: SessionUserView | None = None
    locale: str


class HealthView(BaseModel):
    status: str = "ok"


class AccountSummaryView(BaseModel):
    user: SessionUserView
    sessions: list[LoginSessionView]
    api_tokens: list[ApiTokenView]


class InvitationDetailsView(BaseModel):
    username: str
    role: str
    expires_at: datetime


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


class AdminProjectUserView(BaseModel):
    id: str
    username: str


class AdminProjectItemView(BaseModel):
    id: str
    name: str
    description: str
    state: str
    visibility: str
    creator: AdminProjectUserView
    member_count: int
    item_count: int


class AdminProjectsView(BaseModel):
    projects: list[AdminProjectItemView]
    total: int
    page: int
    per_page: int


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
    action: str
    target_type: str
    target_id: str | None = None
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


class AdminItemsView(BaseModel):
    items: list[ItemSearchView]
    total: int
    page: int
    per_page: int
    storage: StorageMetricsView


class AdminAuditView(BaseModel):
    events: list[AdminAuditEventView]
    total: int
    page: int
    per_page: int


class AdminWorkflowsView(BaseModel):
    workflows: list[WorkflowSummaryView]


class AdminSettingsView(BaseModel):
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


class DashboardRecentItemView(BaseModel):
    item: ItemSearchView
    last_read_at: datetime


class DashboardProjectView(BaseModel):
    id: str
    name: str
    visibility: str


class DashboardView(BaseModel):
    new_items: list[ItemSearchView]
    recent_items: list[DashboardRecentItemView]
    projects: list[DashboardProjectView]
    session_count: int


class ItemWorkspacePermissionsView(BaseModel):
    edit: bool
    delete: bool


class ItemWorkspaceCountsView(BaseModel):
    revisions: int
    attachments: int
    annotations: int
    discussion: int


class ItemTagView(BaseModel):
    id: str
    name: str


class ItemOwnerView(BaseModel):
    id: str
    username: str


class ItemIdentifierView(BaseModel):
    provider: str
    value: str


class ItemLatestRevisionView(BaseModel):
    id: str
    original_name: str
    size: int
    page_count: int | None = None
    processing_state: str


class ItemWorkspaceView(BaseModel):
    item: ItemSearchView
    permissions: ItemWorkspacePermissionsView
    counts: ItemWorkspaceCountsView
    tags: list[ItemTagView]
    owner: ItemOwnerView
    identifiers: list[ItemIdentifierView]
    latest_revision: ItemLatestRevisionView | None = None


class ItemOrganizeProjectView(BaseModel):
    id: str
    name: str
    role: str
    assigned: bool


class TagMatrixGroupView(BaseModel):
    letter: str
    tags: list[ItemTagView]
    names: list[str]


class TagMatrixView(BaseModel):
    groups: list[TagMatrixGroupView]
    assigned_ids: list[str]
    recommended_ids: list[str]
    suggested_names: list[str]
    suggested_single_words: list[str]
    suggested_phrases: list[str]
    recommendation_state: str
    recommendation_error: str | None = None


class ItemOrganizeView(BaseModel):
    item: ItemSearchView
    permissions: ItemWorkspacePermissionsView
    tags: list[ItemTagView]
    projects: list[ItemOrganizeProjectView]
    tag_matrix: TagMatrixView


class PdfViewerRevisionView(BaseModel):
    id: str
    original_name: str
    page_count: int | None = None
    processing_state: str
    page_geometry: list[list[float]]
    content_url: str


class PdfViewerProjectView(BaseModel):
    id: str
    name: str


class PdfViewerView(BaseModel):
    item: ItemSearchView
    editable: bool
    annotation_author: str
    revision: PdfViewerRevisionView
    projects: list[PdfViewerProjectView]


class CitationKeyPreviewView(BaseModel):
    key: str


class AnnotationExportCreatedView(BaseModel):
    id: str
    state: str
    status_url: str


class ImportBatchRetryView(BaseModel):
    id: str
    status: str
    workflow_id: str | None = None


class ImportBatchView(BaseModel):
    id: str
    file_format: str
    status: str
    workflow_id: str | None = None
    records: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    created_at: datetime


class DuplicatesReviewView(BaseModel):
    groups: list[list[ItemSearchView]]
