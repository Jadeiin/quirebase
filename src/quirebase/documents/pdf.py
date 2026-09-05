from __future__ import annotations

import re
from datetime import UTC, tzinfo
from typing import TYPE_CHECKING

import pymupdf

from quirebase.core.timezones import server_timezone

if TYPE_CHECKING:
    from collections.abc import Iterable
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
_LINE_ENDING_NAMES = {value: key for key, value in LINE_ENDINGS.items()}

_NATIVE_KIND = {
    "Highlight": "highlight",
    "Underline": "underline",
    "StrikeOut": "strikeout",
    "Text": "note",
    "FreeText": "free_text",
    "Ink": "ink",
    "Square": "rectangle",
    "Circle": "ellipse",
    "Line": "line",
}


def _hex_color(value: object) -> str | None:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return None
    try:
        channels = [max(0, min(255, round(float(channel) * 255))) for channel in value[:3]]
    except (TypeError, ValueError):
        return None
    return f"#{channels[0]:02X}{channels[1]:02X}{channels[2]:02X}"


def _annotation_style(annotation: pymupdf.Annot) -> dict:
    colors = annotation.colors or {}
    border = annotation.border or {}
    return {
        "stroke_color": _hex_color(colors.get("stroke")),
        "fill_color": _hex_color(colors.get("fill")),
        "text_color": _hex_color(colors.get("stroke")),
        "opacity": (
            float(annotation.opacity)
            if annotation.opacity is not None and float(annotation.opacity) >= 0
            else 1.0
        ),
        "stroke_width": max(0.0, min(20.0, float(border.get("width") or 1))),
        "dash_pattern": [
            max(0.001, min(100.0, float(value)))
            for value in (border.get("dashes") or ())
            if isinstance(value, (int, float)) and float(value) > 0
        ][:10],
    }


def _canonical_rect(page: pymupdf.Page, rect: pymupdf.Rect) -> dict[str, float]:
    crop = pdf_crop_box(page)
    normalized = rect.normalize()
    # Canonical coordinates intentionally follow the viewer's crop-local convention:
    # x is measured from the crop's left edge and y from its bottom edge.
    x = normalized.x0 - crop.x0
    y = crop.height - (normalized.y1 - crop.y0)
    return {
        "x": max(0.0, float(x)),
        "y": max(0.0, float(y)),
        "width": max(0.001, float(normalized.width)),
        "height": max(0.001, float(normalized.height)),
    }


def _canonical_point(page: pymupdf.Page, point: object) -> dict[str, float]:
    crop = pdf_crop_box(page)
    x, y = float(point[0]), float(point[1])  # type: ignore[index]
    return {"x": max(-1_000_000.0, x - crop.x0), "y": crop.height - (y - crop.y0)}


def _rect_from_points(page: pymupdf.Page, points: Iterable[object]) -> dict[str, float]:
    values = [_canonical_point(page, point) for point in points]
    if not values:
        return _canonical_rect(page, page.rect)
    left = min(point["x"] for point in values)
    bottom = min(point["y"] for point in values)
    right = max(point["x"] for point in values)
    top = max(point["y"] for point in values)
    return {
        "x": max(0.0, left),
        "y": max(0.0, bottom),
        "width": max(0.001, right - left),
        "height": max(0.001, top - bottom),
    }


def parse_native_annotations(path: Path) -> list[dict]:
    """Parse supported native PDF markup into transport-neutral Annotation values.

    Unsupported objects are deliberately skipped. Callers can still inspect the
    source with :func:`native_annotation_diagnostics` when they need diagnostics.
    """
    parsed, _diagnostics = _parse_native_annotations(path)
    return parsed


def parse_pdf_annotations(path: Path) -> tuple[list[dict], list[dict]]:
    """Return supported annotations and non-blocking diagnostics."""
    return _parse_native_annotations(path)


def native_annotation_diagnostics(path: Path) -> list[dict]:
    return _parse_native_annotations(path)[1]


def _parse_native_annotations(path: Path) -> tuple[list[dict], list[dict]]:
    parsed: list[dict] = []
    diagnostics: list[dict] = []
    with pymupdf.open(path) as document:
        for page_index, page in enumerate(document):
            for annotation in list(page.annots() or ()):
                subtype = annotation.type[1]
                kind = _NATIVE_KIND.get(subtype)
                if kind is None:
                    diagnostics.append({
                        "page": page_index + 1,
                        "subtype": subtype,
                        "result": "skipped",
                        "reason": "unsupported subtype",
                    })
                    continue
                try:
                    payload: dict = {"type": kind, "style": _annotation_style(annotation)}
                    rect = _canonical_rect(page, annotation.rect)
                    selected_text = None
                    if kind in {"highlight", "underline", "strikeout"}:
                        vertices = list(annotation.vertices or ())
                        segment_rects = [
                            _rect_from_points(page, vertices[index : index + 4])
                            for index in range(0, len(vertices), 4)
                            if vertices[index : index + 4]
                        ]
                        payload["rect"] = _rect_from_points(page, vertices) if vertices else rect
                        payload["segment_rects"] = segment_rects or [rect]
                        selected_text = None
                    elif kind == "free_text":
                        text = annotation.info.get("content", "") or ""
                        payload.update({
                            "rect": rect,
                            "text": text,
                            "font_family": "Helvetica",
                            "font_size": 12,
                            "alignment": "left",
                        })
                    elif kind == "ink":
                        raw_paths = annotation.vertices or ()
                        if (
                            raw_paths
                            and isinstance(raw_paths[0], (tuple, list))
                            and raw_paths[0]
                            and isinstance(raw_paths[0][0], (tuple, list))
                        ):
                            paths = [
                                [_canonical_point(page, point) for point in path]
                                for path in raw_paths
                            ]
                        else:
                            paths = (
                                [[_canonical_point(page, point) for point in raw_paths]]
                                if raw_paths
                                else [[{"x": rect["x"], "y": rect["y"]}]]
                            )
                        payload.update({"rect": rect, "paths": paths})
                    elif kind in {"line", "arrow"}:
                        line = tuple(annotation.vertices or ())
                        if len(line) < 2:
                            line = (annotation.rect.tl, annotation.rect.br)
                        start, end = line[0], line[1]
                        endings = tuple(annotation.line_ends or (0, 0))
                        payload.update({
                            "rect": rect,
                            "start": _canonical_point(page, start),
                            "end": _canonical_point(page, end),
                            "start_ending": _LINE_ENDING_NAMES.get(endings[0], "none"),
                            "end_ending": _LINE_ENDING_NAMES.get(endings[1], "none"),
                        })
                        if any(
                            ending
                            in {
                                LINE_ENDINGS["open_arrow"],
                                LINE_ENDINGS["closed_arrow"],
                                LINE_ENDINGS["reverse_open_arrow"],
                                LINE_ENDINGS["reverse_closed_arrow"],
                            }
                            for ending in endings
                        ):
                            kind = "arrow"
                            payload["type"] = kind
                    else:
                        payload["rect"] = rect
                    info = annotation.info
                    body = info.get("subject") if kind == "free_text" else info.get("content")
                    parsed.append({
                        "page_index": page_index,
                        "kind": kind,
                        "body": body or None,
                        "selected_text": selected_text,
                        "payload": payload,
                        "subtype": subtype,
                        "result": "imported",
                    })
                except (TypeError, ValueError, IndexError, KeyError) as error:
                    diagnostics.append({
                        "page": page_index + 1,
                        "subtype": subtype,
                        "result": "skipped",
                        "reason": str(error),
                    })
    return parsed, diagnostics


def strip_native_annotations(source: Path, output: Path) -> int:
    """Write a derived PDF with page markup removed, preserving links/widgets."""
    with pymupdf.open(source) as document:
        removed = 0
        for page in document:
            annotations = list(page.annots() or ())
            for annotation in annotations:
                page.delete_annot(annotation)
                removed += 1
        output.parent.mkdir(parents=True, exist_ok=True)
        document.save(output, garbage=4, deflate=True)
    return removed


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
