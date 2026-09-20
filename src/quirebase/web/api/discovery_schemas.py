from __future__ import annotations

from pydantic import BaseModel, Field

from quirebase.library import DiscoveryClause


class DiscoverySearchRequest(BaseModel):
    provider: str
    clauses: list[DiscoveryClause]
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=10, ge=1, le=100)
    sort: str = "relevance"
    year_from: int | None = Field(default=None, ge=1000, le=9999)
    year_to: int | None = Field(default=None, ge=1000, le=9999)


class DiscoveryProviderView(BaseModel):
    id: str
    name: str
