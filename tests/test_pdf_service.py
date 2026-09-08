from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pymupdf
import pytest

from quirebase.documents.pdf import (
    _hex_color,
    create_thumbnail,
    export_annotations,
    extract_doi,
    inspect_pdf,
    parse_pdf_annotations,
    strip_native_annotations,
    validate_pdf_container,
)
from quirebase.models import PdfAnnotation


def test_extracts_doi_from_early_pdf_text(tmp_path):
    source = tmp_path / "doi.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Published article https://doi.org/10.1234/example.2026")
    document.save(source)
    document.close()

    assert extract_doi(source) == "10.1234/example.2026"


def sample_pdf(path, *, native_annotation=False):
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        if native_annotation:
            source_annotation = page.add_text_annot((250, 40), "Source annotation")
            source_annotation.update()
        document.save(path)


def test_pymupdf_inspection_and_thumbnail(tmp_path):
    source = tmp_path / "source.pdf"
    thumbnail = tmp_path / "thumb.png"
    sample_pdf(source)

    validate_pdf_container(source)
    pages, text, geometry = inspect_pdf(source)
    create_thumbnail(source, thumbnail)

    assert pages == 1
    assert text == ""
    assert geometry == [[0.0, 0.0, 300.0, 400.0]]
    assert thumbnail.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_strip_native_annotations_writes_clean_derived_pdf(tmp_path):
    source = tmp_path / "native.pdf"
    derived = tmp_path / "stripped.pdf"
    sample_pdf(source, native_annotation=True)

    assert strip_native_annotations(source, derived) == 1
    with pymupdf.open(source) as original, pymupdf.open(derived) as clean:
        assert list(original[0].annots())
        assert list(clean[0].annots() or ()) == []


def test_parse_native_annotations_preserves_freetext_metadata_and_crop_coordinates(tmp_path):
    source = tmp_path / "native.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        page.set_cropbox(pymupdf.Rect(20, 30, 280, 370))
        free_text = page.add_freetext_annot(
            pymupdf.Rect(50, 60, 120, 100),
            "Visible text",
            fontsize=18,
            fontname="TiRo",
            text_color=(1, 0, 0),
            align=2,
            border_width=0,
        )
        free_text.set_info(subject="Canonical body")
        free_text.update()
        document.xref_set_key(free_text.xref, "C", "[0 0 1]")
        page.add_stamp_annot(pymupdf.Rect(140, 160, 180, 200), stamp=0)
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    free_text = next(item for item in parsed if item["kind"] == "free_text")
    assert free_text["body"] == "Canonical body"
    assert free_text["payload"]["text"] == "Visible text"
    assert free_text["payload"]["rect"]["x"] == 50
    assert free_text["payload"]["rect"]["y"] == 240
    assert free_text["payload"]["font_family"] == "Times-Roman"
    assert free_text["payload"]["font_size"] == 18
    assert free_text["payload"]["alignment"] == "right"
    assert free_text["payload"]["style"]["stroke_width"] == 0
    assert free_text["payload"]["style"]["stroke_color"] == "#0000FF"
    assert free_text["payload"]["style"]["text_color"] == "#FF0000"
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "Stamp",
            "result": "skipped",
            "reason": "unsupported subtype",
        }
    ]


def test_parse_native_ink_annotations(tmp_path):
    source = tmp_path / "ink.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        ink = page.add_ink_annot([[(10, 20), (30, 40), (50, 20)]])
        ink.update()
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert diagnostics == []
    assert parsed[0]["kind"] == "ink"
    assert parsed[0]["payload"]["paths"] == [
        [
            {"x": 10.0, "y": 380.0},
            {"x": 30.0, "y": 360.0},
            {"x": 50.0, "y": 380.0},
        ]
    ]


@pytest.mark.parametrize(
    "flag",
    [
        pymupdf.PDF_ANNOT_IS_INVISIBLE,
        pymupdf.PDF_ANNOT_IS_HIDDEN,
        pymupdf.PDF_ANNOT_IS_NO_VIEW,
    ],
)
def test_parse_native_annotations_skips_annotations_that_are_not_viewable(tmp_path, flag):
    source = tmp_path / f"hidden-{flag}.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        native = page.add_text_annot((20, 30), "Suppressed")
        native.set_flags(flag)
        native.update()
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert parsed == []
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "Text",
            "result": "skipped",
            "reason": "annotation is not viewable",
        }
    ]


def test_parse_native_annotations_skips_replies(tmp_path):
    source = tmp_path / "reply.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        parent = page.add_text_annot((20, 30), "Parent")
        parent.update()
        reply = page.add_text_annot((40, 50), "Reply")
        reply.set_irt_xref(parent.xref)
        reply.update()
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert [item["body"] for item in parsed] == ["Parent"]
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "Text",
            "result": "skipped",
            "reason": "annotation replies are unsupported",
        }
    ]


def test_parse_native_annotations_skips_non_default_note_icons(tmp_path):
    source = tmp_path / "comment-icon.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        note = page.add_text_annot((20, 30), "Comment icon")
        note.set_name("Comment")
        note.update()
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert parsed == []
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "Text",
            "result": "skipped",
            "reason": "note icon is unsupported",
        }
    ]


def test_parse_native_annotations_skips_freetext_callouts(tmp_path):
    source = tmp_path / "callout.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        callout = page.add_freetext_annot(pymupdf.Rect(20, 30, 120, 70), "Callout")
        callout.update()
        document.xref_set_key(callout.xref, "IT", "/FreeTextCallout")
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert parsed == []
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "FreeText",
            "result": "skipped",
            "reason": "FreeText callouts are unsupported",
        }
    ]


@pytest.mark.parametrize("dashes", [[3, 0], [1] * 11])
def test_parse_native_annotations_skips_unrepresentable_dash_patterns(tmp_path, dashes):
    source = tmp_path / f"unsupported-dashes-{len(dashes)}.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        shape = page.add_rect_annot(pymupdf.Rect(20, 30, 120, 70))
        shape.set_border(width=2, dashes=dashes)
        shape.update()
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert parsed == []
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "Square",
            "result": "skipped",
            "reason": "dash pattern is not representable",
        }
    ]


def test_parse_native_annotations_bounds_text_markup_segments(tmp_path):
    source = tmp_path / "oversized-highlight.pdf"
    quad = pymupdf.Quad((10, 10), (20, 10), (10, 20), (20, 20))
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        highlight = page.add_highlight_annot([quad] * 501)
        highlight.update()
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert parsed == []
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "Highlight",
            "result": "skipped",
            "reason": "text markup annotations support at most 500 segments",
        }
    ]


def test_parse_native_annotations_skips_non_rectangular_text_markup(tmp_path):
    source = tmp_path / "skewed-highlight.pdf"
    skewed_quad = pymupdf.Quad((10, 10), (20, 12), (12, 20), (22, 22))
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        highlight = page.add_highlight_annot(skewed_quad)
        highlight.update()
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert parsed == []
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "Highlight",
            "result": "skipped",
            "reason": "non-rectangular text markup is unsupported",
        }
    ]


def test_parse_native_annotations_bounds_freetext_before_returning_payload(tmp_path):
    source = tmp_path / "oversized-freetext.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        free_text = page.add_freetext_annot(pymupdf.Rect(20, 30, 120, 70), "x" * 20_001)
        free_text.update()
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert parsed == []
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "FreeText",
            "result": "skipped",
            "reason": "annotation text exceeds 20000 characters",
        }
    ]


def test_parse_native_annotations_skips_rotated_freetext(tmp_path):
    source = tmp_path / "rotated-freetext.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        free_text = page.add_freetext_annot(pymupdf.Rect(20, 30, 120, 70), "Rotated")
        free_text.update()
        document.xref_set_key(free_text.xref, "Rotate", "90")
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert parsed == []
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "FreeText",
            "result": "skipped",
            "reason": "rotated FreeText annotations are unsupported",
        }
    ]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("IT", "/LineDimension"),
        ("Cap", "true"),
        ("LL", "12"),
        ("LLE", "3"),
    ],
)
def test_parse_native_annotations_skips_line_measurement_and_caption_features(tmp_path, key, value):
    source = tmp_path / f"line-{key}.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        line = page.add_line_annot((20, 30), (120, 70))
        line.update()
        document.xref_set_key(line.xref, key, value)
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert parsed == []
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "Line",
            "result": "skipped",
            "reason": "line measurement or caption features are unsupported",
        }
    ]


def test_parse_native_annotations_bounds_ink_points_before_returning_payload(tmp_path):
    source = tmp_path / "oversized-ink.pdf"
    points = [(float(index % 250), float(index // 250)) for index in range(10_001)]
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        ink = page.add_ink_annot([points])
        ink.update()
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert parsed == []
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "Ink",
            "result": "skipped",
            "reason": "ink annotations support at most 10000 points",
        }
    ]


def test_parse_native_annotations_bounds_ink_paths_before_returning_payload(tmp_path):
    source = tmp_path / "oversized-ink-paths.pdf"
    paths = [[(float(index), 20.0), (float(index), 21.0)] for index in range(101)]
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        ink = page.add_ink_annot(paths)
        ink.update()
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert parsed == []
    assert diagnostics == [
        {
            "page": 1,
            "subtype": "Ink",
            "result": "skipped",
            "reason": "ink annotations support at most 100 paths",
        }
    ]


@pytest.mark.parametrize(
    ("components", "expected"),
    [
        ((0.5,), "#808080"),
        ((0.0, 1.0, 1.0, 0.0), "#FF0000"),
    ],
)
def test_annotation_colors_convert_grayscale_and_cmyk(components, expected):
    assert _hex_color(components) == expected


STYLE = {
    "stroke_color": "#3366CC",
    "fill_color": None,
    "text_color": "#112233",
    "opacity": 0.7,
    "stroke_width": 2,
    "dash_pattern": [4, 2],
}


def annotation(kind: str, payload: dict, *, body: str = "Review this") -> PdfAnnotation:
    return PdfAnnotation(
        file_revision_id="revision",
        page_index=0,
        author_id="author",
        kind=kind,
        scope="private",
        body=body,
        payload={"type": kind, "style": STYLE, **payload},
        created_at=datetime(2026, 8, 20, 9, 30, tzinfo=UTC),
        updated_at=datetime(2026, 8, 20, 9, 31, tzinfo=UTC),
    )


def test_export_writes_all_canonical_annotations_without_touching_source(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "annotated.pdf"
    sample_pdf(source, native_annotation=True)
    original = source.read_bytes()
    segment_rects = [
        {"x": 20, "y": 280, "width": 80, "height": 20},
        {"x": 20, "y": 240, "width": 60, "height": 20},
    ]
    mark_rect = {"x": 20, "y": 240, "width": 80, "height": 60}
    annotations = [
        annotation(kind, {"rect": mark_rect, "segment_rects": segment_rects})
        for kind in ("highlight", "underline", "strikeout")
    ]
    annotations.extend([
        annotation("note", {"rect": {"x": 120, "y": 250, "width": 24, "height": 24}}),
        annotation(
            "free_text",
            {
                "rect": {"x": 30, "y": 170, "width": 120, "height": 40},
                "text": "Visible text",
                "font_family": "Helvetica",
                "font_size": 12,
                "alignment": "center",
            },
            body="Free text comment",
        ),
        annotation(
            "ink",
            {
                "rect": {"x": 30, "y": 100, "width": 100, "height": 40},
                "paths": [[{"x": 30, "y": 100}, {"x": 80, "y": 140}, {"x": 130, "y": 100}]],
            },
        ),
        annotation("rectangle", {"rect": {"x": 160, "y": 250, "width": 80, "height": 50}}),
        annotation("ellipse", {"rect": {"x": 160, "y": 180, "width": 80, "height": 50}}),
        annotation(
            "line",
            {
                "rect": {"x": 160, "y": 130, "width": 80, "height": 20},
                "start": {"x": 160, "y": 130},
                "end": {"x": 240, "y": 150},
            },
        ),
        annotation(
            "arrow",
            {
                "rect": {"x": 160, "y": 80, "width": 80, "height": 20},
                "start": {"x": 160, "y": 80},
                "end": {"x": 240, "y": 100},
                "start_ending": "circle",
                "end_ending": "reverse_open_arrow",
            },
        ),
    ])

    export_annotations(
        source,
        output,
        annotations,
        author_names={"author": "alice"},
        display_timezone=ZoneInfo("Asia/Shanghai"),
    )

    with pymupdf.open(output) as document:
        page = document[0]
        exported = list(page.annots())
        subtypes = [record.type[1] for record in exported]
        arrow = [record for record in exported if record.type[1] == "Line"][-1]
        highlight = next(record for record in exported if record.type[1] == "Highlight")
        free_text = next(record for record in exported if record.type[1] == "FreeText")
        assert any(record.info["content"] == "Source annotation" for record in exported)
        assert set(subtypes) == {
            "Highlight",
            "Underline",
            "StrikeOut",
            "Text",
            "FreeText",
            "Ink",
            "Square",
            "Circle",
            "Line",
        }
        assert subtypes.count("Line") == 2
        assert len(highlight.vertices) == 8
        assert highlight.info["title"] == "alice"
        assert highlight.info["content"] == "Review this"
        assert highlight.info["creationDate"] == "D:20260820173000+08'00'"
        assert free_text.info["content"] == "Visible text"
        assert free_text.info["subject"] == "Free text comment"
        assert free_text.border["width"] == pytest.approx(2)
        assert free_text.border["dashes"] == (4, 2)
        assert document.xref_get_key(free_text.xref, "C")[1] == "[.2 .4 .8]"
        assert arrow.line_ends == (
            pymupdf.PDF_ANNOT_LE_CIRCLE,
            pymupdf.PDF_ANNOT_LE_R_OPEN_ARROW,
        )
    assert source.read_bytes() == original


def test_parse_native_line_arrow_intent_maps_to_arrow(tmp_path):
    source = tmp_path / "line-arrow-intent.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        line = page.add_line_annot((20, 30), (120, 70))
        line.update()
        document.xref_set_key(line.xref, "IT", "/LineArrow")
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert diagnostics == []
    assert parsed[0]["kind"] == "arrow"
    assert parsed[0]["payload"]["type"] == "arrow"


def test_geometry_preserves_pdf_crop_box_across_rotation(tmp_path):
    source = tmp_path / "cropped.pdf"
    with pymupdf.open() as document:
        first = document.new_page(width=300, height=400)
        first.set_cropbox(pymupdf.Rect(20, 30, 280, 370))
        first.set_rotation(90)
        document.new_page(width=612, height=792)
        document.save(source)

    pages, _text, geometry = inspect_pdf(source)

    assert pages == 2
    assert geometry == [[20.0, 30.0, 280.0, 370.0], [0.0, 0.0, 612.0, 792.0]]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("kind", ["rectangle", "ellipse"])
def test_canonical_export_is_crop_local_and_rotation_independent(tmp_path, rotation, kind):
    source = tmp_path / f"cropped-{kind}-{rotation}.pdf"
    output = tmp_path / f"cropped-{kind}-{rotation}-annotated.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        page.set_cropbox(pymupdf.Rect(20, 30, 280, 370))
        page.set_rotation(rotation)
        document.save(source)

    record = annotation(
        kind,
        {"rect": {"x": 10, "y": 20, "width": 30, "height": 40}},
    )
    export_annotations(source, output, [record])

    with pymupdf.open(output) as document:
        page = document[0]
        exported = next(page.annots())
        # PyMuPDF expands a 2pt rectangle border by one point on every side.
        assert exported.rect == pymupdf.Rect(9, 279, 41, 321)

    parsed, diagnostics = parse_pdf_annotations(output)

    assert diagnostics == []
    assert parsed[0]["payload"]["rect"] == {
        "x": 10.0,
        "y": 20.0,
        "width": 30.0,
        "height": 40.0,
    }


def test_parse_native_shape_uses_asymmetric_rectangle_differences(tmp_path):
    source = tmp_path / "asymmetric-rd.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        shape = page.add_rect_annot(pymupdf.Rect(10, 20, 50, 80))
        shape.update()
        document.xref_set_key(shape.xref, "Rect", "[10 320 50 380]")
        document.xref_set_key(shape.xref, "RD", "[1 2 3 4]")
        document.save(source)

    parsed, diagnostics = parse_pdf_annotations(source)

    assert diagnostics == []
    assert parsed[0]["payload"]["rect"] == {
        "x": 11.0,
        "y": 324.0,
        "width": 36.0,
        "height": 54.0,
    }
