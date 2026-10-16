from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field


class IdentifiersImportRequest(BaseModel):
    identifiers: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        min_length=1, max_length=50
    )
    provider: str = "auto"
