from __future__ import annotations

import math
import re
from datetime import UTC, tzinfo
from typing import TYPE_CHECKING

import pymupdf

from quirebase.core.timezones import server_timezone
from quirebase.documents.schemas import (
    MAX_ANNOTATION_TEXT_LENGTH,
    MAX_INK_PATHS,
    MAX_INK_POINTS,
    MAX_NATIVE_ANNOTATIONS,
    MAX_NATIVE_GEOMETRY_POINTS,
    MAX_NATIVE_TEXT_CHARS,
    MAX_SEGMENT_RECTS,
)

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
_UNVIEWABLE_ANNOTATION_FLAGS = (
    _pymupdf_integer_constant("PDF_ANNOT_IS_INVISIBLE")
    | _pymupdf_integer_constant("PDF_ANNOT_IS_HIDDEN")
    | _pymupdf_integer_constant("PDF_ANNOT_IS_NO_VIEW")
)
_SIGNATURE_WIDGET_TYPE = _pymupdf_integer_constant("PDF_WIDGET_TYPE_SIGNATURE")


def _hex_color(value: object) -> str | None:
    if not isinstance(value, (tuple, list)) or not value:
        return None
    try:
        channels = [max(0.0, min(1.0, float(channel))) for channel in value]
    except (TypeError, ValueError):
        return None
    if len(channels) == 1:
        rgb = [channels[0]] * 3
    elif len(channels) == 3:
        rgb = channels
    elif len(channels) == 4:
        cyan, magenta, yellow, key = channels
        rgb = [
            (1 - cyan) * (1 - key),
            (1 - magenta) * (1 - key),
            (1 - yellow) * (1 - key),
        ]
    else:
        return None
    return "#{}{}{}".format(*(f"{round(channel * 255):02X}" for channel in rgb))


def _xref_array_color(annotation: pymupdf.Annot, key: str) -> str | None:
    value_type, value = annotation.parent.parent.xref_get_key(annotation.xref, key)
    if value_type != "array":
        return None
    try:
        channels = tuple(float(channel) for channel in value.strip("[]").split())
    except ValueError:
        return None
    return _hex_color(channels)


def _default_appearance_color(annotation: pymupdf.Annot) -> str | None:
    value_type, value = annotation.parent.parent.xref_get_key(annotation.xref, "DA")
    if value_type != "string":
        return None
    channels: tuple[float, ...] | None = None
    tokens = value.split()
    operators = {"g": 1, "rg": 3, "k": 4}
    for index, token in enumerate(tokens):
        count = operators.get(token)
        if count is None or index < count:
            continue
        try:
            channels = tuple(float(channel) for channel in tokens[index - count : index])
        except ValueError:
            continue
    return _hex_color(channels)


def _annotation_style(annotation: pymupdf.Annot) -> dict:
    colors = annotation.colors or {}
    border = annotation.border or {}
    border_width = border.get("width")
    if border_width is not None:
        try:
            border_width = float(border_width)
        except (TypeError, ValueError) as error:
            raise ValueError("border width is not representable") from error
        if not math.isfinite(border_width) or not 0 <= border_width <= 20:
            raise ValueError("border width is not representable")
    dash_pattern = border.get("dashes") or ()
    if len(dash_pattern) > 10 or any(
        not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
        or float(value) > 100
        for value in dash_pattern
    ):
        raise ValueError("dash pattern is not representable")
    stroke_color = _hex_color(colors.get("stroke"))
    text_color = stroke_color
    if annotation.type[1] == "FreeText":
        stroke_color = _xref_array_color(annotation, "C")
        text_color = _default_appearance_color(annotation)
    return {
        "stroke_color": stroke_color,
        "fill_color": _hex_color(colors.get("fill")),
        "text_color": text_color,
        "opacity": (
            float(annotation.opacity)
            if annotation.opacity is not None and float(annotation.opacity) >= 0
            else 1.0
        ),
        "stroke_width": max(
            0.0,
            float(1 if border_width is None else border_width),
        ),
        "dash_pattern": [float(value) for value in dash_pattern],
    }


def _has_unsupported_border_effects(annotation: pymupdf.Annot) -> bool:
    border = annotation.border or {}
    style = border.get("style")
    if style not in (None, "S", "D"):
        return True
    clouds = border.get("clouds")
    return clouds not in (None, -1)


def _free_text_format(annotation: pymupdf.Annot) -> dict[str, str | float]:
    font_family = "Helvetica"
    font_size = 12.0
    supported_fonts = {
        "Helvetica": "Helvetica",
        "Helv": "Helvetica",
        "Times-Roman": "Times-Roman",
        "TiRo": "Times-Roman",
        "Courier": "Courier",
        "Cour": "Courier",
    }
    text = annotation.get_text("dict")
    formats: set[tuple[str, float]] = set()
    for block in text.get("blocks", ()):
        for line in block.get("lines", ()):
            for span in line.get("spans", ()):
                native_font = str(span.get("font", "")).rsplit("+", 1)[-1]
                if native_font in supported_fonts:
                    font_family = supported_fonts[native_font]
                native_size = span.get("size")
                if isinstance(native_size, (int, float)) and 1 <= native_size <= 144:
                    font_size = float(native_size)
                formats.add((font_family, font_size))
    if len(formats) > 1:
        raise ValueError("mixed FreeText formatting is unsupported")

    alignment = "left"
    value_type, value = annotation.parent.parent.xref_get_key(annotation.xref, "Q")
    if value_type == "int":
        alignment = {0: "left", 1: "center", 2: "right"}.get(int(value), "left")
    return {
        "font_family": font_family,
        "font_size": font_size,
        "alignment": alignment,
    }


def _canonical_rect(page: pymupdf.Page, rect: pymupdf.Rect) -> dict[str, float]:
    crop = pdf_crop_box(page)
    normalized = rect.normalize()
    # Canonical coordinates intentionally follow the viewer's crop-local convention:
    # x is measured from the crop's left edge and y from its bottom edge.
    x = normalized.x0
    y = crop.height - normalized.y1
    width = max(0.001, float(normalized.width))
    height = max(0.001, float(normalized.height))
    if x < 0 or y < 0 or x + width > crop.width or y + height > crop.height:
        raise ValueError("annotation rectangle lies outside the crop box")
    return {"x": float(x), "y": float(y), "width": width, "height": height}


def _xref_number_array(annotation: pymupdf.Annot, key: str) -> tuple[float, ...] | None:
    value_type, value = annotation.parent.parent.xref_get_key(annotation.xref, key)
    if value_type != "array":
        return None
    try:
        return tuple(float(component) for component in value.strip("[]").split())
    except ValueError:
        return None


def _canonical_shape_rect(page: pymupdf.Page, annotation: pymupdf.Annot) -> dict[str, float]:
    rect = annotation.rect.normalize()
    differences = _xref_number_array(annotation, "RD")
    if differences is not None and len(differences) == 4:
        left, top, right, bottom = differences
        if all(component >= 0 for component in differences):
            inner = pymupdf.Rect(
                rect.x0 + left,
                rect.y0 + top,
                rect.x1 - right,
                rect.y1 - bottom,
            )
            if not inner.is_empty:
                rect = inner
    return _canonical_rect(page, rect)


def _is_axis_aligned_quad(points: Iterable[object]) -> bool:
    coordinates = [_point_coordinates(point) for point in points]
    if len(coordinates) != 4:
        return False
    x_values = [x for x, _y in coordinates]
    y_values = [y for _x, y in coordinates]
    quad_rect = pymupdf.Rect(min(x_values), min(y_values), max(x_values), max(y_values))
    expected = sorted([
        (quad_rect.x0, quad_rect.y0),
        (quad_rect.x0, quad_rect.y1),
        (quad_rect.x1, quad_rect.y0),
        (quad_rect.x1, quad_rect.y1),
    ])
    actual = sorted(coordinates)
    return all(
        math.isclose(actual_x, expected_x, abs_tol=1e-6)
        and math.isclose(actual_y, expected_y, abs_tol=1e-6)
        for (actual_x, actual_y), (expected_x, expected_y) in zip(actual, expected, strict=True)
    )


def _has_unsupported_line_features(document: pymupdf.Document, annotation: pymupdf.Annot) -> bool:
    intent_type, intent = document.xref_get_key(annotation.xref, "IT")
    if intent_type != "null" and not (intent_type == "name" and intent == "/LineArrow"):
        return True
    caption_type, caption = document.xref_get_key(annotation.xref, "Cap")
    if caption_type != "null" and not (caption_type == "bool" and caption == "false"):
        return True
    return any(
        document.xref_get_key(annotation.xref, key)[0] != "null"
        for key in ("LL", "LLE", "LLO", "CP", "CO", "Measure")
    )


def _has_nonzero_freetext_rotation(document: pymupdf.Document, annotation: pymupdf.Annot) -> bool:
    value_type, value = document.xref_get_key(annotation.xref, "Rotate")
    if value_type == "null":
        return False
    if value_type not in {"int", "real"}:
        return True
    try:
        return not math.isclose(float(value), 0.0, abs_tol=1e-9)
    except ValueError:
        return True


def _point_coordinates(point: object) -> tuple[float, float]:
    if hasattr(point, "x") and hasattr(point, "y"):
        return float(point.x), float(point.y)
    return float(point[0]), float(point[1])  # type: ignore[index]


def _is_point_like(value: object) -> bool:
    try:
        _point_coordinates(value)
    except (TypeError, ValueError, IndexError, KeyError):
        return False
    return True


def _canonical_ink_paths(
    page: pymupdf.Page, annotation: pymupdf.Annot
) -> list[list[dict[str, float]]]:
    raw_paths = annotation.vertices or ()
    source_paths = (raw_paths,) if raw_paths and _is_point_like(raw_paths[0]) else raw_paths
    if len(source_paths) > MAX_INK_PATHS:
        raise ValueError(f"ink annotations support at most {MAX_INK_PATHS} paths")
    point_count = sum(len(path) for path in source_paths)
    if point_count > MAX_INK_POINTS:
        raise ValueError(f"ink annotations support at most {MAX_INK_POINTS} points")
    if not source_paths or any(not path for path in source_paths):
        raise ValueError("ink paths cannot be empty")
    return [[_canonical_point(page, point) for point in path] for path in source_paths]


def _canonical_point(page: pymupdf.Page, point: object) -> dict[str, float]:
    crop = pdf_crop_box(page)
    x, y = _point_coordinates(point)
    return {"x": max(-1_000_000.0, x), "y": crop.height - y}


def _rect_from_points(page: pymupdf.Page, points: Iterable[object]) -> dict[str, float]:
    values = [_canonical_point(page, point) for point in points]
    if not values:
        return _canonical_rect(page, page.rect)
    left = min(point["x"] for point in values)
    bottom = min(point["y"] for point in values)
    right = max(point["x"] for point in values)
    top = max(point["y"] for point in values)
    width = max(0.001, right - left)
    height = max(0.001, top - bottom)
    crop = pdf_crop_box(page)
    if left < 0 or bottom < 0 or right > crop.width or top > crop.height:
        raise ValueError("annotation rectangle lies outside the crop box")
    return {"x": left, "y": bottom, "width": width, "height": height}


def _canonical_text_markup_segments(
    page: pymupdf.Page, vertices: Iterable[object]
) -> tuple[dict[str, float], list[dict[str, float]]]:
    """Convert native text-markup quads while enforcing the canonical segment bound.

    Keep the limit check ahead of any per-quad validation or geometry conversion so
    malformed PDFs cannot force an oversized durable workflow result.
    """
    native_vertices: list[object] = []
    for point in vertices:
        # Consume at most one point beyond the representable payload.  This keeps
        # hostile PDFs from materializing an unbounded vertex list in the worker.
        if len(native_vertices) >= MAX_SEGMENT_RECTS * 4:
            raise ValueError(
                f"text markup annotations support at most {MAX_SEGMENT_RECTS} segments"
            )
        native_vertices.append(point)
    segment_rects: list[dict[str, float]] = []
    for index in range(0, len(native_vertices), 4):
        quad = native_vertices[index : index + 4]
        if not quad or not _is_axis_aligned_quad(quad):
            raise ValueError("non-rectangular text markup is unsupported")
        segment_rects.append(_rect_from_points(page, quad))
    enclosing = _rect_from_points(page, native_vertices)
    return enclosing, segment_rects


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
        native_annotation_count = 0
        native_geometry_points = 0
        native_text_chars = 0
        for page_index, page in enumerate(document):
            for annotation in page.annots() or ():
                native_annotation_count += 1
                if native_annotation_count > MAX_NATIVE_ANNOTATIONS:
                    diagnostics.append({
                        "page": page_index + 1,
                        "subtype": "*",
                        "result": "skipped",
                        "reason": (
                            f"PDF contains more than {MAX_NATIVE_ANNOTATIONS} native annotations"
                        ),
                    })
                    return parsed, diagnostics
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
                if annotation.flags & _UNVIEWABLE_ANNOTATION_FLAGS:
                    diagnostics.append({
                        "page": page_index + 1,
                        "subtype": subtype,
                        "result": "skipped",
                        "reason": "annotation is not viewable",
                    })
                    continue
                if annotation.irt_xref:
                    diagnostics.append({
                        "page": page_index + 1,
                        "subtype": subtype,
                        "result": "skipped",
                        "reason": "annotation replies are unsupported",
                    })
                    continue
                icon_type, icon = document.xref_get_key(annotation.xref, "Name")
                if subtype == "Text" and icon_type == "name" and icon != "/Note":
                    diagnostics.append({
                        "page": page_index + 1,
                        "subtype": subtype,
                        "result": "skipped",
                        "reason": "note icon is unsupported",
                    })
                    continue
                intent_type, intent = document.xref_get_key(annotation.xref, "IT")
                if subtype == "FreeText" and intent_type == "name" and intent == "/FreeTextCallout":
                    diagnostics.append({
                        "page": page_index + 1,
                        "subtype": subtype,
                        "result": "skipped",
                        "reason": "FreeText callouts are unsupported",
                    })
                    continue
                try:
                    raw_vertices = annotation.vertices or ()
                    if subtype == "Ink":
                        geometry_cost = (
                            len(raw_vertices)
                            if raw_vertices and _is_point_like(raw_vertices[0])
                            else sum(len(path) for path in raw_vertices)
                        )
                    else:
                        geometry_cost = len(raw_vertices)
                    native_geometry_points += geometry_cost
                    if native_geometry_points > MAX_NATIVE_GEOMETRY_POINTS:
                        diagnostics.append({
                            "page": page_index + 1,
                            "subtype": subtype,
                            "result": "skipped",
                            "reason": (
                                "PDF native annotation geometry exceeds "
                                f"{MAX_NATIVE_GEOMETRY_POINTS} points"
                            ),
                        })
                        return parsed, diagnostics
                    content = annotation.info.get("content", "") or ""
                    subject = (
                        annotation.info.get("subject", "") or "" if subtype == "FreeText" else ""
                    )
                    native_text_chars += len(content) + len(subject)
                    if native_text_chars > MAX_NATIVE_TEXT_CHARS:
                        diagnostics.append({
                            "page": page_index + 1,
                            "subtype": subtype,
                            "result": "skipped",
                            "reason": (
                                "PDF native annotation text exceeds "
                                f"{MAX_NATIVE_TEXT_CHARS} characters"
                            ),
                        })
                        return parsed, diagnostics
                    if _has_unsupported_border_effects(annotation):
                        raise ValueError("border style or cloudy effects are unsupported")
                    if subtype == "FreeText" and _has_nonzero_freetext_rotation(
                        document, annotation
                    ):
                        raise ValueError("rotated FreeText annotations are unsupported")
                    if subtype == "Line" and _has_unsupported_line_features(document, annotation):
                        raise ValueError("line measurement or caption features are unsupported")
                    payload: dict = {"type": kind, "style": _annotation_style(annotation)}
                    rect: dict[str, float] | None = None
                    selected_text = None
                    if kind in {"highlight", "underline", "strikeout"}:
                        enclosing_rect, segment_rects = _canonical_text_markup_segments(
                            page, annotation.vertices or ()
                        )
                        if not segment_rects:
                            rect = _canonical_rect(page, annotation.rect)
                        payload["rect"] = enclosing_rect if segment_rects else rect
                        payload["segment_rects"] = segment_rects or [rect]
                        payload["style"]["fill_color"] = payload["style"]["stroke_color"]
                        selected_text = None
                    elif kind == "free_text":
                        rect = _canonical_rect(page, annotation.rect)
                        text = annotation.info.get("content", "") or ""
                        if len(text) > MAX_ANNOTATION_TEXT_LENGTH:
                            raise ValueError(
                                f"annotation text exceeds {MAX_ANNOTATION_TEXT_LENGTH} characters"
                            )
                        payload.update({
                            "rect": rect,
                            "text": text,
                            **_free_text_format(annotation),
                        })
                    elif kind == "ink":
                        paths = _canonical_ink_paths(page, annotation)
                        rect = _canonical_rect(page, annotation.rect)
                        payload.update({
                            "rect": rect,
                            "paths": paths,
                        })
                    elif kind in {"line", "arrow"}:
                        rect = _canonical_rect(page, annotation.rect)
                        line = tuple(raw_vertices)
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
                        if (intent_type == "name" and intent == "/LineArrow") or any(
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
                        rect = _canonical_shape_rect(page, annotation)
                        payload["rect"] = rect
                    info = annotation.info
                    body = info.get("subject") if kind == "free_text" else info.get("content")
                    if body and len(body) > MAX_ANNOTATION_TEXT_LENGTH:
                        raise ValueError(
                            f"annotation text exceeds {MAX_ANNOTATION_TEXT_LENGTH} characters"
                        )
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
        for page in document:
            for widget in page.widgets() or ():
                if widget.field_type != _SIGNATURE_WIDGET_TYPE:
                    continue
                value_type, value = document.xref_get_key(widget.xref, "V")
                if value_type in {"dict", "xref"} and value.strip() not in {"", "null"}:
                    raise ValueError(
                        "signed PDFs cannot be stripped without invalidating signatures"
                    )
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
