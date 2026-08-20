from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pymupdf

from quirebase.models import PdfAnnotation, PdfAnnotationSegment
from quirebase.pipeline.inspection import (
    create_thumbnail,
    export_annotations,
    extract_doi,
    inspect_pdf,
    validate_pdf_container,
)


def test_extracts_doi_from_early_pdf_text(tmp_path):
    source = tmp_path / "doi.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Published article https://doi.org/10.1234/example.2026")
    document.save(source)
    document.close()

    assert extract_doi(source) == "10.1234/example.2026"


def sample_pdf(path):
    with pymupdf.open() as document:
        document.new_page(width=300, height=400)
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


def test_export_writes_standard_annotations_without_touching_source(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "annotated.pdf"
    sample_pdf(source)
    original = source.read_bytes()
    highlight = PdfAnnotation(
        file_revision_id="revision",
        author_id="author",
        kind="highlight",
        color="yellow",
        body="My highlight comment",
        selected_text="Selected source text",
        created_at=datetime(2026, 8, 20, 9, 30, tzinfo=UTC),
        updated_at=datetime(2026, 8, 20, 9, 31, tzinfo=UTC),
    )
    highlight.segments = [
        PdfAnnotationSegment(
            page_index=0,
            ordinal=0,
            x1=20,
            y1=300,
            x2=100,
            y2=300,
            x3=20,
            y3=280,
            x4=100,
            y4=280,
        )
    ]
    highlight.segments.append(
        PdfAnnotationSegment(
            page_index=0,
            ordinal=1,
            x1=20,
            y1=260,
            x2=80,
            y2=260,
            x3=20,
            y3=240,
            x4=80,
            y4=240,
        )
    )
    note = PdfAnnotation(
        file_revision_id="revision",
        author_id="author",
        kind="note",
        body="Review this",
        created_at=datetime(2026, 8, 20, 9, 32, tzinfo=UTC),
        updated_at=datetime(2026, 8, 20, 9, 33, tzinfo=UTC),
    )
    note.segments = [PdfAnnotationSegment(page_index=0, ordinal=0, anchor_x=120, anchor_y=250)]
    underline = PdfAnnotation(
        file_revision_id="revision",
        author_id="author",
        kind="underline",
        color="red",
        body="My underline comment",
        selected_text="Underlined source text",
        created_at=datetime(2026, 8, 20, 9, 34, tzinfo=UTC),
        updated_at=datetime(2026, 8, 20, 9, 35, tzinfo=UTC),
    )
    underline.segments = [
        PdfAnnotationSegment(
            page_index=0,
            ordinal=0,
            x1=30,
            y1=240,
            x2=130,
            y2=240,
            x3=30,
            y3=220,
            x4=130,
            y4=220,
        )
    ]
    underline.segments.append(
        PdfAnnotationSegment(
            page_index=0,
            ordinal=1,
            x1=30,
            y1=200,
            x2=100,
            y2=200,
            x3=30,
            y3=180,
            x4=100,
            y4=180,
        )
    )

    export_annotations(
        source,
        output,
        [highlight, note, underline],
        author_names={"author": "alice"},
        display_timezone=ZoneInfo("Asia/Shanghai"),
    )

    with pymupdf.open(output) as document:
        page = document[0]
        exported = list(page.annots())
        subtypes = [annotation.type[1] for annotation in exported]
        info = {annotation.type[1]: annotation.info for annotation in exported}
        vertices = {annotation.type[1]: annotation.vertices for annotation in exported}
    assert "Highlight" in subtypes
    assert "Underline" in subtypes
    assert "Text" in subtypes
    assert subtypes.count("Highlight") == 1
    assert subtypes.count("Underline") == 1
    assert len(vertices["Highlight"]) == 8
    assert len(vertices["Underline"]) == 8
    assert info["Highlight"]["title"] == "alice"
    assert info["Highlight"]["content"] == "My highlight comment"
    assert info["Highlight"]["creationDate"] == "D:20260820173000+08'00'"
    assert info["Highlight"]["modDate"] == "D:20260820173100+08'00'"
    assert info["Text"]["creationDate"] == "D:20260820173200+08'00'"
    assert info["Text"]["modDate"] == "D:20260820173300+08'00'"
    assert info["Underline"]["title"] == "alice"
    assert info["Underline"]["content"] == "My underline comment"
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


def test_cross_page_text_annotation_exports_one_pdf_annotation_per_page(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "annotated.pdf"
    with pymupdf.open() as document:
        document.new_page(width=300, height=400)
        document.new_page(width=300, height=400)
        document.save(source)
    annotation = PdfAnnotation(
        file_revision_id="revision",
        author_id="author",
        kind="highlight",
        color="yellow",
        body="Cross-page note",
        created_at=datetime(2026, 8, 20, 9, 30, tzinfo=UTC),
        updated_at=datetime(2026, 8, 20, 9, 31, tzinfo=UTC),
    )
    annotation.segments = [
        PdfAnnotationSegment(
            page_index=0,
            ordinal=0,
            x1=20,
            y1=300,
            x2=100,
            y2=300,
            x3=20,
            y3=280,
            x4=100,
            y4=280,
        ),
        PdfAnnotationSegment(
            page_index=1,
            ordinal=1,
            x1=20,
            y1=300,
            x2=100,
            y2=300,
            x3=20,
            y3=280,
            x4=100,
            y4=280,
        ),
    ]

    export_annotations(
        source,
        output,
        [annotation],
        author_names={"author": "alice"},
        display_timezone=ZoneInfo("Asia/Shanghai"),
    )

    with pymupdf.open(output) as document:
        annotation_counts = []
        infos = []
        vertex_counts = []
        for page in document:
            annotations = list(page.annots())
            annotation_counts.append(len(annotations))
            infos.extend(dict(annotation.info) for annotation in annotations)
            vertex_counts.extend(len(annotation.vertices) for annotation in annotations)
    assert annotation_counts == [1, 1]
    assert all(info["content"] == "Cross-page note" for info in infos)
    assert vertex_counts == [4, 4]
