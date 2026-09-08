from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from quirebase.library import DiscoveryClause, ItemMetadata


@dataclass(frozen=True)
class ItemCreateRequest(ItemMetadata):
    # Optional stable operation identity; repeating a create request with the
    # same value returns the original Item instead of creating a duplicate.
    operation_id: str | None = None


class ItemUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    metadata: ItemMetadata


class NameRequest(BaseModel):
    name: str


class ProjectCreateRequest(BaseModel):
    name: str
    visibility: Literal["private", "public"] = "private"
    description: str = Field(default="", max_length=2000)


class ProjectVisibilityRequest(BaseModel):
    visibility: Literal["private", "public"]


class ProjectDescriptionRequest(BaseModel):
    description: str = Field(max_length=2000)


class ProjectDeleteRequest(BaseModel):
    confirmation: str


class ProjectMemberRequest(BaseModel):
    username: str
    role: Literal["owner", "editor", "viewer"] = "viewer"


class TagSetRequest(BaseModel):
    tag_ids: list[str] = Field(default_factory=list)
    new_names: list[str] = Field(default_factory=list)
    # The whole-collection replacement is guarded by the Item version the
    # selection was based on, so concurrent editors cannot drop each other's
    # assignments silently.
    expected_version: int = Field(ge=1)


class DiscussionRequest(BaseModel):
    body: str


class DiscoverySearchRequest(BaseModel):
    provider: str
    clauses: list[DiscoveryClause]
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=10, ge=1, le=100)
    sort: str = "relevance"
    year_from: int | None = None
    year_to: int | None = None
