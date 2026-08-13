from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SegmentInput(BaseModel):
    page_index: int = Field(ge=0)
    quad_points: list[float] | None = Field(default=None, min_length=8, max_length=8)
    anchor_x: float | None = None
    anchor_y: float | None = None

    @model_validator(mode="after")
    def valid_geometry(self):
        if self.quad_points is None and (self.anchor_x is None or self.anchor_y is None):
            raise ValueError("segment needs quad_points or an anchor")
        return self


class AnnotationCreate(BaseModel):
    revision_id: str
    kind: Literal["highlight", "note"]
    scope: Literal["private", "project"] = "private"
    project_id: str | None = None
    color: Literal["yellow", "green", "blue", "red"] = "yellow"
    body: str | None = Field(default=None, max_length=20_000)
    selected_text: str | None = Field(default=None, max_length=50_000)
    segments: list[SegmentInput] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_scope_and_kind(self):
        if (self.scope == "project") != (self.project_id is not None):
            raise ValueError("project_id is required exactly for project scope")
        if self.kind == "highlight" and any(
            segment.quad_points is None for segment in self.segments
        ):
            raise ValueError("highlights require quad points")
        if self.kind == "note" and (len(self.segments) != 1 or self.segments[0].anchor_x is None):
            raise ValueError("notes require one anchor")
        return self


class AnnotationUpdate(BaseModel):
    version: int = Field(ge=1)
    scope: Literal["private", "project"] | None = None
    project_id: str | None = None
    color: Literal["yellow", "green", "blue", "red"] | None = None
    body: str | None = Field(default=None, max_length=20_000)


class ExportCreate(BaseModel):
    revision_id: str
    project_id: str | None = None
    include_private: bool = True
