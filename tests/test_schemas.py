from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from quirebase.documents.schemas import AnnotationCreate, AnnotationPayload, AnnotationReplyCreate


def base(kind: str, payload: dict) -> dict:
    return {
        "id": str(uuid4()),
        "revision_id": "revision",
        "page_index": 0,
        "kind": kind,
        "payload": {"type": kind, "rect": {"x": 1, "y": 2, "width": 20, "height": 10}, **payload},
    }


@pytest.mark.parametrize(
    ("kind", "extra"),
    [
        ("highlight", {"segment_rects": [{"x": 1, "y": 2, "width": 20, "height": 10}]}),
        ("underline", {"segment_rects": [{"x": 1, "y": 2, "width": 20, "height": 10}]}),
        ("strikeout", {"segment_rects": [{"x": 1, "y": 2, "width": 20, "height": 10}]}),
        ("note", {}),
        (
            "free_text",
            {"text": "Visible", "font_family": "Helvetica", "font_size": 12, "alignment": "left"},
        ),
        ("ink", {"paths": [[{"x": 1, "y": 2}, {"x": 5, "y": 6}]]}),
        ("rectangle", {}),
        ("ellipse", {}),
        ("line", {"start": {"x": 1, "y": 2}, "end": {"x": 21, "y": 12}}),
        ("arrow", {"start": {"x": 1, "y": 2}, "end": {"x": 21, "y": 12}}),
    ],
)
def test_all_canonical_annotation_payloads(kind, extra):
    command = AnnotationCreate.model_validate(base(kind, extra))
    assert command.kind.value == kind
    assert command.payload.type == kind


def test_line_endings_accept_all_standard_pdf_styles_and_keep_kind_defaults():
    line = AnnotationCreate.model_validate(
        base(
            "line",
            {
                "start": {"x": 1, "y": 2},
                "end": {"x": 21, "y": 12},
                "start_ending": "circle",
                "end_ending": "reverse_open_arrow",
            },
        )
    )
    arrow = AnnotationCreate.model_validate(
        base(
            "arrow",
            {
                "start": {"x": 1, "y": 2},
                "end": {"x": 21, "y": 12},
            },
        )
    )
    assert (line.payload.start_ending, line.payload.end_ending) == (
        "circle",
        "reverse_open_arrow",
    )
    assert (arrow.payload.start_ending, arrow.payload.end_ending) == ("none", "closed_arrow")


def test_project_scope_requires_project():
    data = base("note", {}) | {"scope": "project"}
    with pytest.raises(ValidationError):
        AnnotationCreate.model_validate(data)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["payload"].update({"vendor": {"arbitrary": True}}),
        lambda data: data["payload"]["rect"].update({"width": 0}),
        lambda data: data["payload"].update({"style": {"opacity": 1.1}}),
        lambda data: data["payload"].update({"style": {"stroke_color": "red"}}),
        lambda data: data.update({"id": "not-a-uuid"}),
    ],
)
def test_canonical_payload_rejects_unknown_or_unbounded_values(mutation):
    data = base("note", {})
    mutation(data)
    with pytest.raises(ValidationError):
        AnnotationCreate.model_validate(data)


def test_kind_must_match_discriminated_payload():
    data = base("note", {})
    data["kind"] = "rectangle"
    with pytest.raises(ValidationError, match="kind must match"):
        AnnotationCreate.model_validate(data)


def test_payload_union_rejects_unsupported_subtype():
    with pytest.raises(ValidationError):
        TypeAdapter(AnnotationPayload).validate_python({
            "type": "polygon",
            "rect": {"x": 1, "y": 2, "width": 20, "height": 10},
        })


def test_annotation_reply_requires_a_uuid_and_nonempty_bounded_body():
    reply = AnnotationReplyCreate.model_validate({"id": str(uuid4()), "body": "Reply"})
    assert reply.body == "Reply"
    for body in ("", "x" * 20_001):
        with pytest.raises(ValidationError):
            AnnotationReplyCreate.model_validate({"id": str(uuid4()), "body": body})
