from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from quirebase.models import ProjectParticipation
from quirebase.web.api.library_schemas import ItemSearchView


class DashboardRecentItemView(BaseModel):
    item: ItemSearchView
    last_read_at: datetime


class DashboardProjectView(BaseModel):
    id: UUID
    name: str
    participation: ProjectParticipation


class DashboardView(BaseModel):
    new_items: list[ItemSearchView]
    recent_items: list[DashboardRecentItemView]
    projects: list[DashboardProjectView]
    session_count: int
