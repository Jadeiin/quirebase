from __future__ import annotations

from datetime import datetime  # ruff: ignore[typing-only-standard-library-import]
from typing import Any

from pydantic import BaseModel, Field


class IdentifierImportRequest(BaseModel):
    identifier: str = Field(min_length=1)
    provider: str = "auto"


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
