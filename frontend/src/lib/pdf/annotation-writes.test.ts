import type { AnnotationEvent } from '@embedpdf/svelte-pdf-viewer';
import {
	PdfAnnotationName,
	PdfAnnotationSubtype,
	type PdfAnnotationObject
} from '@embedpdf/models';
import { describe, expect, it, vi } from 'vitest';
import type { CanonicalAnnotation, CanonicalReply } from '$lib/pdf/annotation-adapter';
import {
	createWriteQueue,
	persistReplyEvent,
	selectNativeAnnotationIds
} from '$lib/pdf/annotation-writes';

const parent = (): CanonicalAnnotation => ({
	id: 'annotation-1',
	revision_id: 'revision-1',
	page_index: 0,
	kind: 'note',
	scope: 'private',
	project_id: null,
	body: 'Parent',
	selected_text: null,
	payload: {
		type: 'note',
		rect: { x: 0, y: 0, width: 10, height: 10 },
		style: {
			stroke_color: null,
			fill_color: null,
			text_color: null,
			opacity: 1,
			stroke_width: 1,
			dash_pattern: []
		}
	},
	version: 1,
	author_display_name: 'Reader',
	editable: true,
	created_at: '2026-01-01T00:00:00Z',
	updated_at: '2026-01-01T00:00:00Z',
	replies: []
});

const replyObject = (contents: string): PdfAnnotationObject =>
	({
		id: 'reply-1',
		pageIndex: 0,
		rect: { origin: { x: 0, y: 0 }, size: { width: 10, height: 10 } },
		type: PdfAnnotationSubtype.TEXT,
		name: PdfAnnotationName.Note,
		contents,
		inReplyToId: 'annotation-1'
	}) as PdfAnnotationObject;

const event = (
	type: 'create' | 'update' | 'delete',
	contents: string
): Exclude<AnnotationEvent, { type: 'loaded' }> => {
	const annotation = replyObject(contents);
	if (type === 'update') {
		return {
			type,
			documentId: 'revision-1',
			annotation,
			pageIndex: 0,
			patch: { contents },
			committed: false
		};
	}
	return { type, documentId: 'revision-1', annotation, pageIndex: 0, committed: false };
};

const savedReply = (body: string, version = 1): CanonicalReply => ({
	id: 'reply-1',
	annotation_id: 'annotation-1',
	body,
	version,
	author_display_name: 'Reader',
	editable: true,
	created_at: '2026-01-01T00:00:00Z',
	updated_at: '2026-01-01T00:00:00Z'
});

describe('annotation write coordination', () => {
	it('keeps imported parent annotations and replies out of the native set', () => {
		const importedIds = new Set(['annotation-1', 'reply-1']);

		expect(
			selectNativeAnnotationIds(['embedded-1', 'annotation-1', 'reply-1'], importedIds)
		).toEqual(['embedded-1']);
	});

	it('persists create, update, delete, and restore reply events', async () => {
		const records = new Map([['annotation-1', parent()]]);
		const tombstones = new Map<string, CanonicalReply>();
		const request = vi.fn(async (path: string, options?: { method?: string; body?: unknown }) => {
			if (path.endsWith('/restore?version=3')) return savedReply('Restored', 4);
			if (options?.method === 'POST') return savedReply('First reply');
			if (options?.method === 'PATCH') return savedReply('Edited reply', 2);
			return undefined;
		});

		await persistReplyEvent({
			event: event('create', 'First reply'),
			itemId: 'item-1',
			records,
			tombstones,
			request
		});
		expect(request).toHaveBeenLastCalledWith('/items/item-1/annotations/annotation-1/replies', {
			method: 'POST',
			body: { id: 'reply-1', body: 'First reply' }
		});

		await persistReplyEvent({
			event: event('update', 'Edited reply'),
			itemId: 'item-1',
			records,
			tombstones,
			request
		});
		expect(request).toHaveBeenLastCalledWith(
			'/items/item-1/annotations/annotation-1/replies/reply-1',
			{ method: 'PATCH', body: { version: 1, body: 'Edited reply' } }
		);

		await persistReplyEvent({
			event: event('delete', 'Edited reply'),
			itemId: 'item-1',
			records,
			tombstones,
			request
		});
		expect(request).toHaveBeenLastCalledWith(
			'/items/item-1/annotations/annotation-1/replies/reply-1?version=2',
			{ method: 'DELETE' }
		);

		await persistReplyEvent({
			event: event('create', 'Restored'),
			itemId: 'item-1',
			records,
			tombstones,
			request
		});
		expect(request).toHaveBeenLastCalledWith(
			'/items/item-1/annotations/annotation-1/replies/reply-1/restore?version=3',
			{ method: 'POST' }
		);
	});

	it('tracks queued and active writes until they settle', async () => {
		let finish!: () => void;
		const queue = createWriteQueue();
		const write = queue.enqueue(
			() =>
				new Promise<void>((resolve) => {
					finish = resolve;
				})
		);

		expect(queue.hasPending()).toBe(true);
		finish();
		await write;
		expect(queue.hasPending()).toBe(false);
	});
});
