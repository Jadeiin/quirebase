from __future__ import annotations

from datetime import datetime  # ruff: ignore[typing-only-standard-library-import]

from pydantic import BaseModel

from quirebase.web.api.library_schemas import ItemSearchView


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
