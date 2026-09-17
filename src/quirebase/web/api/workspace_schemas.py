from __future__ import annotations

from datetime import datetime  # ruff: ignore[typing-only-standard-library-import] - Pydantic resolves it
from typing import Any

from pydantic import BaseModel, Field

from quirebase.web.api.library_schemas import ItemSearchView


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
