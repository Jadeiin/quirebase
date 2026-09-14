from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from quirebase.library import DiscoveryClause, ItemMetadata


class ItemUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    metadata: ItemMetadata


class NameRequest(BaseModel):
    name: str = Field(max_length=240)


class ProjectCreateRequest(BaseModel):
    name: str = Field(max_length=240)
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
    year_from: int | None = None
    year_to: int | None = None
