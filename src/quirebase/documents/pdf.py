from __future__ import annotations

import re
from datetime import UTC, tzinfo
from typing import TYPE_CHECKING

import pymupdf

from quirebase.core.timezones import server_timezone

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from quirebase.models import PdfAnnotation

COLORS = {
    "yellow": (1.0, 0.92, 0.2),
    "green": (0.35, 0.85, 0.4),
    "blue": (0.35, 0.65, 1.0),
    "red": (1.0, 0.35, 0.35),
}

PDF_DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


def pdf_crop_box(page: pymupdf.Page) -> pymupdf.Rect:
    media = page.mediabox
    crop = page.cropbox
    return pymupdf.Rect(
        crop.x0,
        media.y0 + media.height - crop.y1,
        crop.x1,
        media.y0 + media.height - crop.y0,
    )


def pdf_point_to_page(page: pymupdf.Page, point: pymupdf.Point) -> pymupdf.Point:
    crop = pdf_crop_box(page)
    local = pymupdf.Point(point.x - crop.x0, point.y - crop.y0)
    return local * page.transformation_matrix


def validate_pdf_container(path: Path) -> None:
    try:
        with pymupdf.open(path) as document:
            if document.needs_pass:
                raise ValueError("password-protected PDFs are not supported")
            if document.page_count < 1:
                raise ValueError("PDF contains no pages")
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("PDF structure is invalid") from error


def inspect_pdf(path: Path) -> tuple[int, str, list[list[float]]]:
    with pymupdf.open(path) as document:
        page_count = document.page_count
        text = [page.get_text("text") for page in document]
        geometry = []
        for page in document:
            pdf_box = pdf_crop_box(page)
            geometry.append([pdf_box.x0, pdf_box.y0, pdf_box.x1, pdf_box.y1])
        return page_count, "\n\f\n".join(text), geometry


def first_doi_from_text(text: str) -> str | None:
    """Return the first plausible DOI found in free text, if any."""
    normalized = re.sub(r"\s+", " ", text or "")
    match = PDF_DOI_PATTERN.search(normalized)
    return match.group(0).rstrip(".,;)]}") if match else None


def extract_doi(path: Path, maximum_pages: int = 8) -> str | None:
    """Extract the first plausible DOI from PDF metadata or early-page text."""
    with pymupdf.open(path) as document:
        candidates = [
            document.metadata.get("subject", ""),
            document.metadata.get("keywords", ""),
        ]
        candidates.extend(
            document[index].get_text("text")
            for index in range(min(document.page_count, maximum_pages))
        )
    for candidate in candidates:
        doi = first_doi_from_text(candidate)
        if doi:
            return doi
    return None


def create_thumbnail(path: Path, output: Path) -> None:
    with pymupdf.open(path) as document:
        if document.page_count == 0:
            raise ValueError("PDF contains no pages")
        page = document[0]
        scale = min(2.0, 128 / max(page.rect.width, 1))
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(output)


def _pdf_date(value: datetime | None, display_timezone: tzinfo | None = None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(display_timezone or server_timezone())
    total_minutes = int((value.utcoffset() or UTC.utcoffset(None)).total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    absolute_minutes = abs(total_minutes)
    return (
        value.strftime("D:%Y%m%d%H%M%S")
        + f"{sign}{absolute_minutes // 60:02d}'{absolute_minutes % 60:02d}'"
    )


def export_annotations(
    source: Path,
    output: Path,
    annotations: list[PdfAnnotation],
    *,
    author_names: dict[str, str] | None = None,
    display_timezone: tzinfo | None = None,
) -> None:
    author_names = author_names or {}
    with pymupdf.open(source) as document:
        if document.needs_pass:
            raise ValueError("password-protected PDFs cannot be exported")
        for record in annotations:
            author_name = author_names.get(record.author_id, "")
            info = {
                "title": author_name,
                "content": record.body or "",
                "creationDate": _pdf_date(record.created_at, display_timezone),
                "modDate": _pdf_date(record.updated_at or record.created_at, display_timezone),
            }
            if record.kind in ("highlight", "underline"):
                quads_by_page: dict[int, list[pymupdf.Quad]] = {}
                for segment in record.segments:
                    values = [
                        segment.x1,
                        segment.y1,
                        segment.x2,
                        segment.y2,
                        segment.x3,
                        segment.y3,
                        segment.x4,
                        segment.y4,
                    ]
                    if any(value is None for value in values):
                        continue
                    page = document[segment.page_index]
                    points = [
                        pdf_point_to_page(page, pymupdf.Point(values[i], values[i + 1]))
                        for i in range(0, 8, 2)
                    ]
                    quad = pymupdf.Quad(*points)
                    quads_by_page.setdefault(segment.page_index, []).append(quad)
                for page_index, quads in quads_by_page.items():
                    page = document[page_index]
                    annotation = (
                        page.add_highlight_annot(quads)
                        if record.kind == "highlight"
                        else page.add_underline_annot(quads)
                    )
                    annotation.set_colors(stroke=COLORS[record.color])
                    annotation.set_info(**info)
                    annotation.update(opacity=0.35 if record.kind == "highlight" else 0.9)
            else:
                segment = record.segments[0]
                page = document[segment.page_index]
                point = pdf_point_to_page(
                    page, pymupdf.Point(segment.anchor_x or 0, segment.anchor_y or 0)
                )
                annotation = page.add_text_annot(point, record.body or "")
                annotation.set_info(**info)
                annotation.update()
        output.parent.mkdir(parents=True, exist_ok=True)
        document.save(output, garbage=4, deflate=True)
