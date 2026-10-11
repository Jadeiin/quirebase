from __future__ import annotations

from pydantic import BaseModel, Field


class IdentifierImportRequest(BaseModel):
    identifier: str = Field(min_length=1)
    provider: str = "auto"
