from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pymupdf
import pytest

from quirebase.documents.pdf import (
    create_thumbnail,
    export_annotations,
    extract_doi,
    inspect_pdf,
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
def test_canonical_export_is_crop_local_and_rotation_independent(tmp_path, rotation):
    source = tmp_path / f"cropped-{rotation}.pdf"
    output = tmp_path / f"cropped-{rotation}-annotated.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        page.set_cropbox(pymupdf.Rect(20, 30, 280, 370))
        page.set_rotation(rotation)
        document.save(source)

    record = annotation(
        "rectangle",
        {"rect": {"x": 10, "y": 20, "width": 30, "height": 40}},
    )
    export_annotations(source, output, [record])

    with pymupdf.open(output) as document:
        page = document[0]
        exported = next(page.annots())
        # PyMuPDF expands a 2pt rectangle border by one point on every side.
        assert exported.rect == pymupdf.Rect(9, 279, 41, 321)
