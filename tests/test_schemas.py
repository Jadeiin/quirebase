import pytest
from pydantic import ValidationError

from quirebase.documents.schemas import AnnotationCreate


def test_project_scope_requires_project():
    with pytest.raises(ValidationError):
        AnnotationCreate(
            revision_id="revision",
            kind="note",
            scope="project",
            body="x",
            segments=[{"page_index": 0, "anchor_x": 1, "anchor_y": 1}],
        )


def test_highlight_requires_quad_points():
    with pytest.raises(ValidationError):
        AnnotationCreate(
            revision_id="revision",
            kind="highlight",
            segments=[{"page_index": 0, "anchor_x": 1, "anchor_y": 1}],
        )
