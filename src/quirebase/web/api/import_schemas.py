from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IdentifierImportRequest(BaseModel):
    identifier: str = Field(min_length=1)
    provider: str = "auto"


class ImportBatchRetryView(BaseModel):
    id: UUID
    status: str
    workflow_id: str | None = None


class ImportBatchView(BaseModel):
    id: UUID
    file_format: str
    status: str
    workflow_id: str | None = None
    records: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    created_at: datetime
