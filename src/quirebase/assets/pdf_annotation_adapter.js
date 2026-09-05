import {
  PdfAnnotationBorderStyle,
  PdfAnnotationLineEnding,
  PdfAnnotationName,
  PdfAnnotationReplyType,
  PdfAnnotationSubtype,
} from "@embedpdf/snippet";

export const createAnnotationAdapter = (pageGeometry) => {
  const lineEndingNames = {
    [PdfAnnotationLineEnding.None]: "none",
    [PdfAnnotationLineEnding.Square]: "square",
    [PdfAnnotationLineEnding.Circle]: "circle",
    [PdfAnnotationLineEnding.Diamond]: "diamond",
    [PdfAnnotationLineEnding.OpenArrow]: "open_arrow",
    [PdfAnnotationLineEnding.ClosedArrow]: "closed_arrow",
    [PdfAnnotationLineEnding.Butt]: "butt",
    [PdfAnnotationLineEnding.ROpenArrow]: "reverse_open_arrow",
    [PdfAnnotationLineEnding.RClosedArrow]: "reverse_closed_arrow",
    [PdfAnnotationLineEnding.Slash]: "slash",
  };
  const vendorLineEndings = Object.fromEntries(
    Object.entries(lineEndingNames).map(([value, name]) => [name, Number(value)]),
  );
  const pageHeight = (pageIndex) => {
    const box = pageGeometry[pageIndex];
    if (!box) throw new Error("missing PDF page geometry");
    return box[3] - box[1];
  };

  const toCanonicalPoint = (point, pageIndex) => ({
    x: point.x,
    y: pageHeight(pageIndex) - point.y,
  });
  const toVendorPoint = (point, pageIndex) => ({
    x: point.x,
    y: pageHeight(pageIndex) - point.y,
  });
  const toCanonicalRect = (rect, pageIndex) => ({
    x: rect.origin.x,
    y: pageHeight(pageIndex) - rect.origin.y - rect.size.height,
    width: rect.size.width,
    height: rect.size.height,
  });
  const toVendorRect = (rect, pageIndex) => ({
    origin: { x: rect.x, y: pageHeight(pageIndex) - rect.y - rect.height },
    size: { width: rect.width, height: rect.height },
  });

  const canonicalColor = (color) => color === "transparent" ? null : (color || null);
  const styleFromVendor = (object) => ({
    stroke_color: canonicalColor(object.strokeColor),
    fill_color: canonicalColor(object.color || object.backgroundColor),
    text_color: canonicalColor(object.fontColor),
    opacity: object.opacity ?? 1,
    stroke_width: object.strokeWidth ?? 1,
    dash_pattern: object.strokeDashArray || [],
  });

  const kindFromVendor = (object) => {
    const kinds = {
      [PdfAnnotationSubtype.HIGHLIGHT]: "highlight",
      [PdfAnnotationSubtype.UNDERLINE]: "underline",
      [PdfAnnotationSubtype.STRIKEOUT]: "strikeout",
      [PdfAnnotationSubtype.TEXT]: "note",
      [PdfAnnotationSubtype.FREETEXT]: "free_text",
      [PdfAnnotationSubtype.INK]: "ink",
      [PdfAnnotationSubtype.SQUARE]: "rectangle",
      [PdfAnnotationSubtype.CIRCLE]: "ellipse",
    };
    if (object.type === PdfAnnotationSubtype.LINE) {
      const arrowEndings = [
        PdfAnnotationLineEnding.OpenArrow,
        PdfAnnotationLineEnding.ClosedArrow,
      ];
      return object.intent === "LineArrow" || arrowEndings.includes(object.lineEndings?.end)
        ? "arrow"
        : "line";
    }
    return kinds[object.type];
  };

  const canonicalFromVendor = (object, pageIndex, existing = null) => {
    const kind = kindFromVendor(object);
    if (!kind || object.intent === "FreeTextCallout" || object.inReplyToId) {
      throw new Error("unsupported annotation type");
    }
    const payload = {
      type: kind,
      rect: toCanonicalRect(object.rect, pageIndex),
      style: styleFromVendor(object),
    };
    if (["highlight", "underline", "strikeout"].includes(kind)) {
      payload.segment_rects = object.segmentRects.map(
        (rect) => toCanonicalRect(rect, pageIndex),
      );
    } else if (kind === "free_text") {
      const fonts = { 0: "Courier", 4: "Helvetica", 8: "Times-Roman" };
      const alignments = { 0: "left", 1: "center", 2: "right" };
      payload.text = object.contents || "";
      payload.font_family = fonts[object.fontFamily] || "Helvetica";
      payload.font_size = object.fontSize || 12;
      payload.alignment = alignments[object.textAlign] || "left";
    } else if (kind === "ink") {
      payload.paths = object.inkList.map((path) => path.points.map(
        (point) => toCanonicalPoint(point, pageIndex),
      ));
    } else if (kind === "line" || kind === "arrow") {
      payload.start = toCanonicalPoint(object.linePoints.start, pageIndex);
      payload.end = toCanonicalPoint(object.linePoints.end, pageIndex);
      payload.start_ending = lineEndingNames[object.lineEndings?.start] || "none";
      payload.end_ending = lineEndingNames[object.lineEndings?.end]
        || (kind === "arrow" ? "closed_arrow" : "none");
    }
    return {
      page_index: pageIndex,
      kind,
      body: kind === "free_text" ? (existing?.body ?? null) : (object.contents || null),
      selected_text: existing?.selected_text
        ?? (["highlight", "underline", "strikeout"].includes(kind)
          && typeof object.custom?.text === "string" ? object.custom.text : null),
      payload,
    };
  };

  const vendorFromCanonical = (annotation) => {
    const { payload } = annotation;
    const pageIndex = annotation.page_index;
    const base = {
      id: annotation.id,
      pageIndex,
      rect: toVendorRect(payload.rect, pageIndex),
      author: annotation.author_display_name,
      contents: annotation.kind === "free_text" ? payload.text : (annotation.body || ""),
      created: new Date(annotation.created_at),
      modified: new Date(annotation.updated_at),
      flags: annotation.editable ? ["print"] : ["print", "readOnly"],
      custom: { quirebase: true },
    };
    const style = payload.style;
    Object.assign(base, {
      strokeColor: style.stroke_color || undefined,
      color: style.fill_color ?? "transparent",
      opacity: style.opacity,
      strokeWidth: style.stroke_width,
      strokeStyle: style.dash_pattern.length
        ? PdfAnnotationBorderStyle.DASHED
        : PdfAnnotationBorderStyle.SOLID,
      strokeDashArray: style.dash_pattern.length ? style.dash_pattern : undefined,
    });
    const types = {
      highlight: PdfAnnotationSubtype.HIGHLIGHT,
      underline: PdfAnnotationSubtype.UNDERLINE,
      strikeout: PdfAnnotationSubtype.STRIKEOUT,
      note: PdfAnnotationSubtype.TEXT,
      free_text: PdfAnnotationSubtype.FREETEXT,
      ink: PdfAnnotationSubtype.INK,
      rectangle: PdfAnnotationSubtype.SQUARE,
      ellipse: PdfAnnotationSubtype.CIRCLE,
      line: PdfAnnotationSubtype.LINE,
      arrow: PdfAnnotationSubtype.LINE,
    };
    base.type = types[annotation.kind];
    if (["highlight", "underline", "strikeout"].includes(annotation.kind)) {
      base.segmentRects = payload.segment_rects.map((rect) => toVendorRect(rect, pageIndex));
    } else if (annotation.kind === "note") {
      base.name = PdfAnnotationName.Note;
    } else if (annotation.kind === "free_text") {
      const fonts = { Courier: 0, Helvetica: 4, "Times-Roman": 8 };
      const alignments = { left: 0, center: 1, right: 2 };
      base.fontFamily = fonts[payload.font_family];
      base.fontSize = payload.font_size;
      base.fontColor = style.text_color || "#000000";
      base.textAlign = alignments[payload.alignment];
      base.verticalAlign = 0;
    } else if (annotation.kind === "ink") {
      base.inkList = payload.paths.map((path) => ({
        points: path.map((point) => toVendorPoint(point, pageIndex)),
      }));
    } else if (annotation.kind === "line" || annotation.kind === "arrow") {
      if (annotation.kind === "arrow") base.intent = "LineArrow";
      base.linePoints = {
        start: toVendorPoint(payload.start, pageIndex),
        end: toVendorPoint(payload.end, pageIndex),
      };
      base.lineEndings = {
        start: vendorLineEndings[payload.start_ending] ?? PdfAnnotationLineEnding.None,
        end: vendorLineEndings[payload.end_ending]
          ?? (annotation.kind === "arrow"
            ? PdfAnnotationLineEnding.ClosedArrow
            : PdfAnnotationLineEnding.None),
      };
    }
    return base;
  };

  const vendorReplyFromCanonical = (annotation, reply) => ({
    id: reply.id,
    pageIndex: annotation.page_index,
    rect: toVendorRect(annotation.payload.rect, annotation.page_index),
    author: reply.author_display_name,
    contents: reply.body,
    created: new Date(reply.created_at),
    modified: new Date(reply.updated_at),
    type: PdfAnnotationSubtype.TEXT,
    name: PdfAnnotationName.Note,
    inReplyToId: annotation.id,
    replyType: PdfAnnotationReplyType.Reply,
    flags: reply.editable ? ["print"] : ["print", "readOnly"],
    custom: { quirebase: true, reply: true },
  });

  return { canonicalFromVendor, vendorFromCanonical, vendorReplyFromCanonical };
};
