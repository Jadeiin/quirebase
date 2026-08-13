import pymupdf

from quirebase.models import PdfAnnotation, PdfAnnotationSegment
from quirebase.pdf_service import (
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
        file_revision_id="revision", author_id="author", kind="highlight", color="yellow"
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
    note = PdfAnnotation(
        file_revision_id="revision", author_id="author", kind="note", body="Review this"
    )
    note.segments = [PdfAnnotationSegment(page_index=0, ordinal=0, anchor_x=120, anchor_y=250)]

    export_annotations(source, output, [highlight, note])

    with pymupdf.open(output) as document:
        subtypes = [annotation.type[1] for annotation in document[0].annots()]
    assert "Highlight" in subtypes
    assert "Text" in subtypes
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
