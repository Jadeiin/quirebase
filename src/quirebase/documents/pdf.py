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

PDF_DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


def _pymupdf_integer_constant(name: str) -> int:
    """Read an integer constant omitted from PyMuPDF's published type interface."""
    value: object = getattr(pymupdf, name)
    if not isinstance(value, int):  # pragma: no cover - guards an upstream API change
        raise TypeError(f"PyMuPDF constant {name} is not an integer")
    return value


LINE_ENDINGS = {
    "none": _pymupdf_integer_constant("PDF_ANNOT_LE_NONE"),
    "square": _pymupdf_integer_constant("PDF_ANNOT_LE_SQUARE"),
    "circle": _pymupdf_integer_constant("PDF_ANNOT_LE_CIRCLE"),
    "diamond": _pymupdf_integer_constant("PDF_ANNOT_LE_DIAMOND"),
    "open_arrow": _pymupdf_integer_constant("PDF_ANNOT_LE_OPEN_ARROW"),
    "closed_arrow": _pymupdf_integer_constant("PDF_ANNOT_LE_CLOSED_ARROW"),
    "butt": _pymupdf_integer_constant("PDF_ANNOT_LE_BUTT"),
    "reverse_open_arrow": _pymupdf_integer_constant("PDF_ANNOT_LE_R_OPEN_ARROW"),
    "reverse_closed_arrow": _pymupdf_integer_constant("PDF_ANNOT_LE_R_CLOSED_ARROW"),
    "slash": _pymupdf_integer_constant("PDF_ANNOT_LE_SLASH"),
}


def pdf_crop_box(page: pymupdf.Page) -> pymupdf.Rect:
    media = page.mediabox
    crop = page.cropbox
    return pymupdf.Rect(
        crop.x0,
        media.y0 + media.height - crop.y1,
        crop.x1,
        media.y0 + media.height - crop.y0,
    )


def canonical_point_to_page(page: pymupdf.Page, point: dict[str, float]) -> pymupdf.Point:
    """Map crop-box-local, bottom-left PDF user space into PyMuPDF page space."""
    crop = pdf_crop_box(page)
    return pymupdf.Point(point["x"], crop.height - point["y"])


def canonical_rect_to_page(page: pymupdf.Page, rect: dict[str, float]) -> pymupdf.Rect:
    first = canonical_point_to_page(page, {"x": rect["x"], "y": rect["y"]})
    second = canonical_point_to_page(
        page,
        {"x": rect["x"] + rect["width"], "y": rect["y"] + rect["height"]},
    )
    return pymupdf.Rect(first, second).normalize()


def _color(value: str | None) -> tuple[float, float, float] | None:
    if value is None:
        return None
    return (
        int(value[1:3], 16) / 255,
        int(value[3:5], 16) / 255,
        int(value[5:7], 16) / 255,
    )


def _apply_annotation_style(annotation: pymupdf.Annot, style: dict) -> None:
    subtype = annotation.type[1]
    if subtype != "FreeText":
        annotation.set_colors(
            stroke=_color(style.get("stroke_color")),
            fill=_color(style.get("fill_color")),
        )
    if subtype in {"Ink", "Square", "Circle", "Line", "FreeText"}:
        annotation.set_border(
            width=style.get("stroke_width", 1),
            dashes=style.get("dash_pattern") or None,
        )
    annotation.update(opacity=style.get("opacity", 1))


def _set_freetext_border_color(
    document: pymupdf.Document, annotation: pymupdf.Annot, color: tuple[float, float, float] | None
) -> None:
    """PyMuPDF cannot set FreeText colors through Annot.set_colors()."""
    if color is None:
        return
    document.xref_set_key(annotation.xref, "C", "[{} {} {}]".format(*color))


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
            payload = record.payload
            info = {
                "title": author_name,
                "content": record.body or "",
                "creationDate": _pdf_date(record.created_at, display_timezone),
                "modDate": _pdf_date(record.updated_at or record.created_at, display_timezone),
            }
            page = document[record.page_index]
            style = payload["style"]
            if record.kind in ("highlight", "underline", "strikeout"):
                quads = []
                for rect in payload["segment_rects"]:
                    upper_left = canonical_point_to_page(
                        page, {"x": rect["x"], "y": rect["y"] + rect["height"]}
                    )
                    upper_right = canonical_point_to_page(
                        page,
                        {"x": rect["x"] + rect["width"], "y": rect["y"] + rect["height"]},
                    )
                    lower_left = canonical_point_to_page(page, {"x": rect["x"], "y": rect["y"]})
                    lower_right = canonical_point_to_page(
                        page,
                        {"x": rect["x"] + rect["width"], "y": rect["y"]},
                    )
                    quads.append(pymupdf.Quad(upper_left, upper_right, lower_left, lower_right))
                factories = {
                    "highlight": page.add_highlight_annot,
                    "underline": page.add_underline_annot,
                    "strikeout": page.add_strikeout_annot,
                }
                annotation = factories[record.kind](quads)
            elif record.kind == "note":
                rect = payload["rect"]
                point = canonical_point_to_page(
                    page, {"x": rect["x"], "y": rect["y"] + rect["height"]}
                )
                annotation = page.add_text_annot(point, record.body or "")
            elif record.kind == "free_text":
                font_names = {"Helvetica": "Helv", "Times-Roman": "TiRo", "Courier": "Cour"}
                alignments = {"left": 0, "center": 1, "right": 2}
                annotation = page.add_freetext_annot(
                    canonical_rect_to_page(page, payload["rect"]),
                    payload["text"],
                    fontsize=payload["font_size"],
                    fontname=font_names[payload["font_family"]],
                    text_color=_color(style.get("text_color")) or (0, 0, 0),
                    fill_color=_color(style.get("fill_color")),
                    border_color=_color(style.get("stroke_color")),
                    border_width=style.get("stroke_width", 1),
                    dashes=style.get("dash_pattern") or None,
                    opacity=style.get("opacity", 1),
                    richtext=True,
                    align=alignments[payload["alignment"]],
                )
                _set_freetext_border_color(document, annotation, _color(style.get("stroke_color")))
                info["content"] = payload["text"]
                if record.body:
                    info["subject"] = record.body
            elif record.kind == "ink":
                paths: list[list[tuple[float, float]]] = []
                for path in payload["paths"]:
                    converted = [canonical_point_to_page(page, point) for point in path]
                    paths.append([(point.x, point.y) for point in converted])
                annotation = page.add_ink_annot(paths)
            elif record.kind == "rectangle":
                annotation = page.add_rect_annot(canonical_rect_to_page(page, payload["rect"]))
            elif record.kind == "ellipse":
                annotation = page.add_circle_annot(canonical_rect_to_page(page, payload["rect"]))
            else:
                annotation = page.add_line_annot(
                    canonical_point_to_page(page, payload["start"]),
                    canonical_point_to_page(page, payload["end"]),
                )
                default_end = "closed_arrow" if record.kind == "arrow" else "none"
                annotation.set_line_ends(
                    LINE_ENDINGS[payload.get("start_ending", "none")],
                    LINE_ENDINGS[payload.get("end_ending", default_end)],
                )
            annotation.set_info(**info)
            _apply_annotation_style(annotation, style)
        output.parent.mkdir(parents=True, exist_ok=True)
        document.save(output, garbage=4, deflate=True)
