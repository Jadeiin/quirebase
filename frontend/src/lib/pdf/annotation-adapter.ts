import {
	PdfAnnotationBorderStyle,
	PdfAnnotationLineEnding,
	PdfAnnotationName,
	PdfAnnotationReplyType,
	PdfAnnotationSubtype,
	type PdfAnnotationObject
} from '@embedpdf/models';

export type Point = { x: number; y: number };
export type CanonicalRect = Point & { width: number; height: number };
export type AnnotationStyle = {
	stroke_color: string | null;
	fill_color: string | null;
	text_color: string | null;
	opacity: number;
	stroke_width: number;
	dash_pattern: number[];
};
export type CanonicalPayload = {
	type: string;
	rect: CanonicalRect;
	style: AnnotationStyle;
	segment_rects?: CanonicalRect[];
	text?: string;
	font_family?: string;
	font_size?: number;
	alignment?: string;
	paths?: Point[][];
	start?: Point;
	end?: Point;
	start_ending?: string;
	end_ending?: string;
};
export type CanonicalReply = {
	id: string;
	annotation_id: string;
	body: string;
	version: number;
	author_display_name: string;
	editable: boolean;
	created_at: string;
	updated_at: string;
};
export type CanonicalAnnotation = {
	id: string;
	revision_id: string;
	page_index: number;
	kind: string;
	scope: 'private' | 'project';
	project_id: string | null;
	body: string | null;
	selected_text: string | null;
	payload: CanonicalPayload;
	version: number;
	author_display_name: string;
	editable: boolean;
	created_at: string;
	updated_at: string;
	replies: CanonicalReply[];
};

type VendorRect = { origin: Point; size: { width: number; height: number } };
type LooseAnnotation = PdfAnnotationObject & {
	backgroundColor?: string;
	color?: string;
	contents?: string;
	custom?: Record<string, unknown>;
	fontColor?: string;
	fontFamily: number;
	fontSize?: number;
	inkList: Array<{ points: Point[] }>;
	intent?: string;
	lineEndings?: { start?: PdfAnnotationLineEnding; end?: PdfAnnotationLineEnding };
	linePoints: { start: Point; end: Point };
	opacity?: number;
	rect: VendorRect;
	segmentRects: VendorRect[];
	strokeColor?: string;
	strokeDashArray?: number[];
	strokeWidth?: number;
	textAlign: number;
};

const lineEndingNames: Record<number, string> = {
	[PdfAnnotationLineEnding.None]: 'none',
	[PdfAnnotationLineEnding.Square]: 'square',
	[PdfAnnotationLineEnding.Circle]: 'circle',
	[PdfAnnotationLineEnding.Diamond]: 'diamond',
	[PdfAnnotationLineEnding.OpenArrow]: 'open_arrow',
	[PdfAnnotationLineEnding.ClosedArrow]: 'closed_arrow',
	[PdfAnnotationLineEnding.Butt]: 'butt',
	[PdfAnnotationLineEnding.ROpenArrow]: 'reverse_open_arrow',
	[PdfAnnotationLineEnding.RClosedArrow]: 'reverse_closed_arrow',
	[PdfAnnotationLineEnding.Slash]: 'slash'
};
const vendorLineEndings = Object.fromEntries(
	Object.entries(lineEndingNames).map(([value, name]) => [name, Number(value)])
);

export function createAnnotationAdapter(pageGeometry: number[][]) {
	const pageHeight = (pageIndex: number) => {
		const box = pageGeometry[pageIndex];
		if (!box || box.length !== 4) throw new Error('missing PDF page geometry');
		return box[3] - box[1];
	};
	const flipPoint = (point: Point, pageIndex: number): Point => ({
		x: point.x,
		y: pageHeight(pageIndex) - point.y
	});
	const toCanonicalRect = (rect: VendorRect, pageIndex: number): CanonicalRect => ({
		x: rect.origin.x,
		y: pageHeight(pageIndex) - rect.origin.y - rect.size.height,
		width: rect.size.width,
		height: rect.size.height
	});
	const toVendorRect = (rect: CanonicalRect, pageIndex: number): VendorRect => ({
		origin: { x: rect.x, y: pageHeight(pageIndex) - rect.y - rect.height },
		size: { width: rect.width, height: rect.height }
	});
	const color = (value: unknown) =>
		value === 'transparent' || typeof value !== 'string' ? null : value;
	const styleFromVendor = (object: LooseAnnotation): AnnotationStyle => ({
		stroke_color: color(object.strokeColor),
		fill_color: color(object.color ?? object.backgroundColor),
		text_color: color(object.fontColor),
		opacity: object.opacity ?? 1,
		stroke_width: object.strokeWidth ?? 1,
		dash_pattern: object.strokeDashArray ?? []
	});
	const kindFromVendor = (object: LooseAnnotation) => {
		const kinds: Partial<Record<PdfAnnotationSubtype, string>> = {
			[PdfAnnotationSubtype.HIGHLIGHT]: 'highlight',
			[PdfAnnotationSubtype.UNDERLINE]: 'underline',
			[PdfAnnotationSubtype.STRIKEOUT]: 'strikeout',
			[PdfAnnotationSubtype.TEXT]: 'note',
			[PdfAnnotationSubtype.FREETEXT]: 'free_text',
			[PdfAnnotationSubtype.INK]: 'ink',
			[PdfAnnotationSubtype.SQUARE]: 'rectangle',
			[PdfAnnotationSubtype.CIRCLE]: 'ellipse'
		};
		if (object.type === PdfAnnotationSubtype.LINE) {
			const end = object.lineEndings?.end;
			return object.intent === 'LineArrow' ||
				(end !== undefined &&
					[PdfAnnotationLineEnding.OpenArrow, PdfAnnotationLineEnding.ClosedArrow].includes(end))
				? 'arrow'
				: 'line';
		}
		return kinds[object.type];
	};

	const canonicalFromVendor = (
		vendor: PdfAnnotationObject,
		pageIndex: number,
		existing?: CanonicalAnnotation
	) => {
		const object = vendor as LooseAnnotation;
		const kind = kindFromVendor(object);
		if (!kind || object.intent === 'FreeTextCallout' || object.inReplyToId) {
			throw new Error('unsupported annotation type');
		}
		const payload: CanonicalPayload = {
			type: kind,
			rect: toCanonicalRect(object.rect, pageIndex),
			style: styleFromVendor(object)
		};
		if (['highlight', 'underline', 'strikeout'].includes(kind)) {
			payload.segment_rects = object.segmentRects.map((rect: VendorRect) =>
				toCanonicalRect(rect, pageIndex)
			);
		} else if (kind === 'free_text') {
			const fonts: Record<number, string> = { 0: 'Courier', 4: 'Helvetica', 8: 'Times-Roman' };
			const alignments: Record<number, string> = { 0: 'left', 1: 'center', 2: 'right' };
			payload.text = object.contents ?? '';
			payload.font_family = fonts[object.fontFamily] ?? 'Helvetica';
			payload.font_size = object.fontSize ?? 12;
			payload.alignment = alignments[object.textAlign] ?? 'left';
		} else if (kind === 'ink') {
			payload.paths = object.inkList.map((path: { points: Point[] }) =>
				path.points.map((point) => flipPoint(point, pageIndex))
			);
		} else if (kind === 'line' || kind === 'arrow') {
			payload.start = flipPoint(object.linePoints.start, pageIndex);
			payload.end = flipPoint(object.linePoints.end, pageIndex);
			const startEnding = object.lineEndings?.start;
			const endEnding = object.lineEndings?.end;
			payload.start_ending =
				startEnding === undefined ? 'none' : (lineEndingNames[startEnding] ?? 'none');
			payload.end_ending =
				endEnding === undefined
					? kind === 'arrow'
						? 'closed_arrow'
						: 'none'
					: (lineEndingNames[endEnding] ?? (kind === 'arrow' ? 'closed_arrow' : 'none'));
		}
		return {
			page_index: pageIndex,
			kind,
			body: kind === 'free_text' ? (existing?.body ?? null) : (object.contents ?? null),
			selected_text:
				existing?.selected_text ??
				(['highlight', 'underline', 'strikeout'].includes(kind) &&
				typeof object.custom?.text === 'string'
					? object.custom.text
					: null),
			payload
		};
	};

	const vendorFromCanonical = (annotation: CanonicalAnnotation): PdfAnnotationObject => {
		const { payload } = annotation;
		const pageIndex = annotation.page_index;
		const style = payload.style;
		const object: Record<string, unknown> = {
			id: annotation.id,
			pageIndex,
			rect: toVendorRect(payload.rect, pageIndex),
			author: annotation.author_display_name,
			contents: annotation.kind === 'free_text' ? payload.text : (annotation.body ?? ''),
			created: new Date(annotation.created_at),
			modified: new Date(annotation.updated_at),
			flags: annotation.editable ? ['print'] : ['print', 'readOnly'],
			custom: { quirebase: true },
			strokeColor: style.stroke_color ?? undefined,
			color: style.fill_color ?? 'transparent',
			opacity: style.opacity,
			strokeWidth: style.stroke_width,
			strokeStyle: style.dash_pattern.length
				? PdfAnnotationBorderStyle.DASHED
				: PdfAnnotationBorderStyle.SOLID,
			strokeDashArray: style.dash_pattern.length ? style.dash_pattern : undefined
		};
		const types: Record<string, PdfAnnotationSubtype> = {
			highlight: PdfAnnotationSubtype.HIGHLIGHT,
			underline: PdfAnnotationSubtype.UNDERLINE,
			strikeout: PdfAnnotationSubtype.STRIKEOUT,
			note: PdfAnnotationSubtype.TEXT,
			free_text: PdfAnnotationSubtype.FREETEXT,
			ink: PdfAnnotationSubtype.INK,
			rectangle: PdfAnnotationSubtype.SQUARE,
			ellipse: PdfAnnotationSubtype.CIRCLE,
			line: PdfAnnotationSubtype.LINE,
			arrow: PdfAnnotationSubtype.LINE
		};
		object.type = types[annotation.kind];
		if (['highlight', 'underline', 'strikeout'].includes(annotation.kind)) {
			object.segmentRects = (payload.segment_rects ?? []).map((rect) =>
				toVendorRect(rect, pageIndex)
			);
		} else if (annotation.kind === 'note') {
			object.name = PdfAnnotationName.Note;
		} else if (annotation.kind === 'free_text') {
			const fonts: Record<string, number> = { Courier: 0, Helvetica: 4, 'Times-Roman': 8 };
			const alignments: Record<string, number> = { left: 0, center: 1, right: 2 };
			object.fontFamily = fonts[payload.font_family ?? 'Helvetica'];
			object.fontSize = payload.font_size ?? 12;
			object.fontColor = style.text_color ?? '#000000';
			object.textAlign = alignments[payload.alignment ?? 'left'];
			object.verticalAlign = 0;
		} else if (annotation.kind === 'ink') {
			object.inkList = (payload.paths ?? []).map((path) => ({
				points: path.map((point) => flipPoint(point, pageIndex))
			}));
		} else if (annotation.kind === 'line' || annotation.kind === 'arrow') {
			if (annotation.kind === 'arrow') object.intent = 'LineArrow';
			object.linePoints = {
				start: flipPoint(payload.start!, pageIndex),
				end: flipPoint(payload.end!, pageIndex)
			};
			object.lineEndings = {
				start: vendorLineEndings[payload.start_ending ?? 'none'] ?? PdfAnnotationLineEnding.None,
				end:
					vendorLineEndings[payload.end_ending ?? 'none'] ??
					(annotation.kind === 'arrow'
						? PdfAnnotationLineEnding.ClosedArrow
						: PdfAnnotationLineEnding.None)
			};
		}
		return object as unknown as PdfAnnotationObject;
	};

	const vendorReplyFromCanonical = (
		annotation: CanonicalAnnotation,
		reply: CanonicalReply
	): PdfAnnotationObject =>
		({
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
			flags: reply.editable ? ['print'] : ['print', 'readOnly'],
			custom: { quirebase: true, reply: true }
		}) as PdfAnnotationObject;

	return { canonicalFromVendor, vendorFromCanonical, vendorReplyFromCanonical };
}
