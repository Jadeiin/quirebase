from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from quirebase.library import DiscoveryClause, ItemMetadata


class ItemUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    metadata: ItemMetadata


class NameRequest(BaseModel):
    name: str


class ProjectMemberRequest(BaseModel):
    username: str
    role: Literal["owner", "editor", "viewer"] = "viewer"


class TagSetRequest(BaseModel):
    tag_ids: list[str] = Field(default_factory=list)
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
