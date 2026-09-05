from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field, model_validator

from quirebase.models import AnnotationKind, AnnotationScope

MAX_COORDINATE = 1_000_000.0
MAX_SEGMENT_RECTS = 500
MAX_INK_PATHS = 100
MAX_INK_POINTS = 10_000
LineEnding = Literal[
    "none",
    "square",
    "circle",
    "diamond",
    "open_arrow",
    "closed_arrow",
    "butt",
    "reverse_open_arrow",
    "reverse_closed_arrow",
    "slash",
]


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Point(CanonicalModel):
    x: float = Field(ge=-MAX_COORDINATE, le=MAX_COORDINATE)
    y: float = Field(ge=-MAX_COORDINATE, le=MAX_COORDINATE)


class Rect(CanonicalModel):
    x: float = Field(ge=0, le=MAX_COORDINATE)
    y: float = Field(ge=0, le=MAX_COORDINATE)
    width: float = Field(gt=0, le=MAX_COORDINATE)
    height: float = Field(gt=0, le=MAX_COORDINATE)


class AnnotationStyle(CanonicalModel):
    stroke_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    fill_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    text_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    opacity: float = Field(default=1.0, ge=0, le=1)
    stroke_width: float = Field(default=1.0, ge=0, le=20)
    dash_pattern: list[float] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def valid_dash_pattern(self):
        if any(
            not math.isfinite(value) or value <= 0 or value > 100 for value in self.dash_pattern
        ):
            raise ValueError("dash pattern values must be finite and between 0 and 100")
        return self


class PayloadBase(CanonicalModel):
    rect: Rect
    style: AnnotationStyle = Field(default_factory=AnnotationStyle)


class TextMarkupPayload(PayloadBase):
    type: Literal["highlight", "underline", "strikeout"]
    segment_rects: list[Rect] = Field(min_length=1, max_length=MAX_SEGMENT_RECTS)


class NotePayload(PayloadBase):
    type: Literal["note"]


class FreeTextPayload(PayloadBase):
    type: Literal["free_text"]
    text: str = Field(max_length=20_000)
    font_family: Literal["Helvetica", "Times-Roman", "Courier"] = "Helvetica"
    font_size: float = Field(default=12, ge=1, le=144)
    alignment: Literal["left", "center", "right"] = "left"


class InkPayload(PayloadBase):
    type: Literal["ink"]
    paths: list[list[Point]] = Field(min_length=1, max_length=MAX_INK_PATHS)

    @model_validator(mode="after")
    def bounded_paths(self):
        if any(not path for path in self.paths):
            raise ValueError("ink paths cannot be empty")
        if sum(len(path) for path in self.paths) > MAX_INK_POINTS:
            raise ValueError(f"ink annotations support at most {MAX_INK_POINTS} points")
        return self


class RectanglePayload(PayloadBase):
    type: Literal["rectangle"]


class EllipsePayload(PayloadBase):
    type: Literal["ellipse"]


class LinePayload(PayloadBase):
    type: Literal["line"]
    start: Point
    end: Point
    start_ending: LineEnding = "none"
    end_ending: LineEnding = "none"


class ArrowPayload(PayloadBase):
    type: Literal["arrow"]
    start: Point
    end: Point
    start_ending: LineEnding = "none"
    end_ending: LineEnding = "closed_arrow"


AnnotationPayload = Annotated[
    TextMarkupPayload
    | NotePayload
    | FreeTextPayload
    | InkPayload
    | RectanglePayload
    | EllipsePayload
    | LinePayload
    | ArrowPayload,
    Field(discriminator="type"),
]


class AnnotationCreate(CanonicalModel):
    id: UUID4
    revision_id: str = Field(min_length=1, max_length=36)
    page_index: int = Field(ge=0)
    kind: AnnotationKind
    scope: AnnotationScope = AnnotationScope.private
    project_id: str | None = Field(default=None, max_length=36)
    body: str | None = Field(default=None, max_length=20_000)
    selected_text: str | None = Field(default=None, max_length=50_000)
    payload: AnnotationPayload

    @model_validator(mode="after")
    def valid_scope_and_kind(self):
        if (self.scope is AnnotationScope.project) != (self.project_id is not None):
            raise ValueError("project_id is required exactly for project scope")
        if self.kind.value != self.payload.type:
            raise ValueError("annotation kind must match payload type")
        return self


class AnnotationUpdate(CanonicalModel):
    version: int = Field(ge=1)
    page_index: int = Field(ge=0)
    kind: AnnotationKind
    scope: AnnotationScope
    project_id: str | None = Field(default=None, max_length=36)
    body: str | None = Field(default=None, max_length=20_000)
    selected_text: str | None = Field(default=None, max_length=50_000)
    payload: AnnotationPayload

    @model_validator(mode="after")
    def valid_scope_and_kind(self):
        if (self.scope is AnnotationScope.project) != (self.project_id is not None):
            raise ValueError("project_id is required exactly for project scope")
        if self.kind.value != self.payload.type:
            raise ValueError("annotation kind must match payload type")
        return self


class AnnotationReplyCreate(CanonicalModel):
    id: UUID4
    body: str = Field(min_length=1, max_length=20_000)


class AnnotationReplyUpdate(CanonicalModel):
    version: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=20_000)


class ExportCreate(BaseModel):
    revision_id: str
    project_id: str | None = None
    include_private: bool = True
    timezone: str | None = None
