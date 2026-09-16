import { PdfAnnotationSubtype } from '@embedpdf/models';
import { describe, expect, it } from 'vitest';
import { createAnnotationAdapter, type CanonicalAnnotation } from '$lib/pdf/annotation-adapter';

const annotation: CanonicalAnnotation = {
	id: '6ca651e8-b815-45e8-8e73-20db3e24d531',
	revision_id: 'revision',
	page_index: 0,
	kind: 'highlight',
	scope: 'private',
	project_id: null,
	body: 'Important',
	selected_text: 'evidence',
	payload: {
		type: 'highlight',
		rect: { x: 20, y: 30, width: 80, height: 12 },
		segment_rects: [{ x: 20, y: 30, width: 80, height: 12 }],
		style: {
			stroke_color: '#f59e0b',
			fill_color: '#fde68a',
			text_color: null,
			opacity: 0.7,
			stroke_width: 1,
			dash_pattern: []
		}
	},
	version: 1,
	author_display_name: 'reader',
	editable: true,
	created_at: '2026-09-16T00:00:00Z',
	updated_at: '2026-09-16T00:00:00Z',
	replies: []
};

describe('canonical EmbedPDF annotation adapter', () => {
	it('round-trips page geometry without changing Quirebase coordinates', () => {
		const adapter = createAnnotationAdapter([[0, 0, 300, 400]]);
		const vendor = adapter.vendorFromCanonical(annotation);

		expect(vendor.type).toBe(PdfAnnotationSubtype.HIGHLIGHT);
		expect(vendor.rect.origin.y).toBe(358);

		const canonical = adapter.canonicalFromVendor(vendor, 0, annotation);
		expect(canonical.kind).toBe('highlight');
		expect(canonical.payload.rect).toEqual(annotation.payload.rect);
		expect(canonical.payload.segment_rects).toEqual(annotation.payload.segment_rects);
		expect(canonical.selected_text).toBe('evidence');
	});
});
