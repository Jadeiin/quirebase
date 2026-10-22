import { describe, expect, it, vi } from 'vitest';
import type {
	AnnotationCapability,
	AnnotationEvent,
	PdfAnnotationObject
} from '@embedpdf/svelte-pdf-viewer';
import type { components } from '#lib/api/schema.js';
import {
	canonicalAnnotationFromView,
	createAnnotationAdapter
} from '#lib/pdf/annotation-adapter.js';
import {
	createAnnotationSync,
	type AnnotationSources,
	type AnnotationSyncStatus
} from '#lib/pdf/annotation-sync.svelte.js';

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('#lib/api/client.js', () => ({ createWorkspaceApi: () => ({ request }) }));

type AnnotationView = components['schemas']['AnnotationView'];
const privateSource: AnnotationSources = { includePrivate: true, projectIds: [] };
const projectSource: AnnotationSources = { includePrivate: false, projectIds: ['project-1'] };
const adapter = createAnnotationAdapter([[0, 0, 300, 400]]);
const annotation = (id: string): AnnotationView => ({
	id,
	revision_id: 'revision-1',
	revision_name: 'paper.pdf',
	page_index: 0,
	kind: 'note',
	scope: 'private',
	project_id: null,
	project_name: null,
	body: 'Server note',
	selected_text: null,
	payload: { type: 'note', rect: { x: 20, y: 30, width: 24, height: 24 } },
	version: 1,
	author_display_name: 'Reader',
	mine: true,
	editable: true,
	authorization: { allowed: [] },
	created_at: '2026-01-01T00:00:00Z',
	updated_at: '2026-01-01T00:00:00Z',
	replies: []
});
const reply = (record: AnnotationView): AnnotationView['replies'][number] => ({
	id: 'reply-1',
	annotation_id: record.id,
	body: 'Restored reply',
	version: 1,
	author_display_name: 'Reader',
	mine: true,
	editable: true,
	created_at: record.created_at,
	updated_at: record.updated_at
});
const list = (
	annotations: AnnotationView[],
	next_cursor: string | null = null,
	total = annotations.length
) => ({
	annotations,
	revisions: [],
	projects: [],
	next_cursor,
	total,
	page: 1,
	per_page: 100
});

function harness() {
	request.mockReset();
	const objects = new Map<string, PdfAnnotationObject>();
	const statuses: AnnotationSyncStatus[] = [];
	const scope = {
		getAnnotations: vi.fn(() => [...objects.values()].map((object) => ({ object }))),
		getAnnotationById: vi.fn((id: string) => {
			const object = objects.get(id);
			return object ? { object } : null;
		}),
		purgeAnnotation: vi.fn((_page: number, id: string) => objects.delete(id)),
		syncAnnotationObject: vi.fn((id: string, patch: Partial<PdfAnnotationObject>) => {
			const object = objects.get(id);
			if (object) objects.set(id, { ...object, ...patch } as PdfAnnotationObject);
		}),
		importAnnotations: vi.fn((rows: { annotation: PdfAnnotationObject }[]) => {
			for (const row of rows) objects.set(row.annotation.id, row.annotation);
		})
	};
	const sync = createAnnotationSync({
		workspaceId: 'workspace-1',
		itemId: 'item-1',
		documentId: 'revision-1',
		pageGeometry: [[0, 0, 300, 400]],
		initialSources: privateSource,
		initialWriteProject: '',
		onStatus: (status) => statuses.push(status)
	});
	sync.attach({ forDocument: () => scope } as unknown as AnnotationCapability);
	async function event(
		type: 'create' | 'update' | 'delete',
		record: AnnotationView,
		replyId?: string
	) {
		const canonical = canonicalAnnotationFromView(record);
		const object = replyId
			? adapter.vendorReplyFromCanonical(
					canonical,
					canonical.replies.find((r) => r.id === replyId)!
				)
			: adapter.vendorFromCanonical(canonical);
		if (type === 'delete') objects.delete(object.id);
		else objects.set(object.id, object);
		sync.handleEvent({
			type,
			annotation: object,
			pageIndex: 0,
			documentId: 'revision-1',
			committed: false,
			...(type === 'update' ? { patch: { contents: object.contents } } : {})
		} as AnnotationEvent);
		await sync.flush();
	}
	return { sync, objects, statuses, event };
}

describe('reader annotation reconciliation', () => {
	for (const recoverySucceeds of [true, false]) {
		it.each([
			['root', 'create'],
			['root', 'update'],
			['root', 'delete'],
			['reply', 'create'],
			['reply', 'update'],
			['reply', 'delete']
		] as const)(
			`retains a failed %s %s after recovery ${recoverySucceeds ? 'succeeds' : 'fails'}`,
			async (target, operation) => {
				const { sync, statuses, event } = harness();
				const record = annotation('failed-write');
				const child = reply(record);
				record.replies = target === 'reply' && operation !== 'create' ? [child] : [];
				const initial = target === 'root' && operation === 'create' ? [] : [record];
				request.mockResolvedValueOnce(list(initial));
				await sync.load(privateSource);
				const failure = new Error('Write unavailable');
				request.mockRejectedValueOnce(failure);
				if (recoverySucceeds) request.mockResolvedValueOnce(list(initial));
				else request.mockRejectedValueOnce(new Error('Recovery unavailable'));
				const draft = {
					...record,
					body: 'Edited note',
					replies: target === 'reply' ? [{ ...child, body: 'Edited reply' }] : []
				};
				await event(operation, draft, target === 'reply' ? child.id : undefined);
				expect(request.mock.calls.at(-1)?.[0]).toBe('GET');
				expect(statuses.slice(-2)).toEqual([
					{ state: target === 'reply' ? 'saving-reply' : 'saving-annotation' },
					{ state: 'sync-failed', reason: failure }
				]);
			}
		);
	}

	it('reports normal reads and a later successful write after failed-write recovery', async () => {
		const { sync, statuses, event } = harness();
		const record = annotation('retry-write');
		request.mockResolvedValueOnce(list([record]));
		await sync.load(privateSource);
		expect(statuses).toEqual([{ state: 'loading' }, { state: 'loaded', count: 1 }]);
		request
			.mockRejectedValueOnce(new Error('Write unavailable'))
			.mockResolvedValueOnce(list([record]));
		await event('update', record);
		expect(statuses.at(-1)?.state).toBe('sync-failed');
		request.mockResolvedValueOnce({ ...record, version: 2 });
		await event('update', record);
		expect(statuses.slice(-2)).toEqual([{ state: 'saving-annotation' }, { state: 'saved' }]);
	});

	it('isolates a root and reply sharing a UUID throughout edit, delete, and Undo', async () => {
		const { sync, objects, event } = harness();
		const record = annotation('6ca651e8-b815-45e8-8e73-20db3e24d531');
		const child = { ...reply(record), id: record.id };
		record.replies = [child];
		const rootObjectId = adapter.annotationObjectId(record.id);
		const replyObjectId = adapter.replyObjectId(child.id);
		request.mockResolvedValueOnce(list([record]));
		await sync.load(privateSource);
		sync.handleEvent({ type: 'loaded', documentId: 'revision-1', total: 0 });
		expect(objects.size).toBe(2);
		expect(objects.get(replyObjectId)?.inReplyToId).toBe(rootObjectId);
		expect(objects.get(rootObjectId)?.flags).not.toContain('readOnly');
		expect(objects.get(replyObjectId)?.flags).not.toContain('readOnly');

		child.body = 'Edited reply';
		request.mockResolvedValueOnce({ ...child, version: 2 });
		await event('update', record, child.id);
		expect(request.mock.calls.at(-1)?.[2]).toMatchObject({
			params: { path: { annotation_id: record.id, reply_id: child.id } },
			body: { version: 1, body: 'Edited reply' }
		});
		expect(objects.get(rootObjectId)?.contents).toBe('Server note');
		expect(objects.get(replyObjectId)?.contents).toBe('Edited reply');

		request.mockResolvedValueOnce({ ok: true });
		await event('delete', record, child.id);
		expect(objects.has(rootObjectId)).toBe(true);
		expect(objects.has(replyObjectId)).toBe(false);
		request.mockResolvedValueOnce({ ...child, version: 4 });
		await event('create', record, child.id);
		expect(request.mock.calls.at(-1)?.[2]).toMatchObject({
			params: { path: { annotation_id: record.id, reply_id: child.id }, query: { version: 3 } }
		});
		expect(objects.size).toBe(2);
		expect(objects.get(replyObjectId)?.inReplyToId).toBe(rootObjectId);

		request.mockResolvedValueOnce({ ...record, body: 'Edited root', version: 2 });
		sync.setWriteProject('another-project');
		await event('update', { ...record, body: 'Edited root' });
		const update = request.mock.calls.at(-1)?.[2];
		expect(update.params.path.annotation_id).toBe(record.id);
		expect(update.body).not.toHaveProperty('scope');
		expect(update.body).not.toHaveProperty('project_id');
		expect(objects.get(rootObjectId)?.contents).toBe('Edited root');
		expect(objects.get(replyObjectId)?.contents).toBe('Edited reply');
	});

	it('retains freshly authored viewer IDs across refresh and history replay', async () => {
		const { sync, objects } = harness();
		const record = annotation('6ca651e8-b815-45e8-8e73-20db3e24d531');
		request.mockResolvedValueOnce(list([])).mockResolvedValueOnce(record);
		await sync.load(privateSource);
		const object = {
			...adapter.vendorFromCanonical(canonicalAnnotationFromView(record)),
			id: record.id
		};
		const created = {
			type: 'create',
			annotation: object,
			pageIndex: 0,
			documentId: 'revision-1',
			committed: false
		} as AnnotationEvent;
		objects.set(object.id, object);
		sync.handleEvent(created);
		await sync.flush();
		expect(request.mock.calls[1][2].body.id).toBe(record.id);
		record.replies = [{ ...reply(record), id: record.id }];
		request.mockResolvedValueOnce(list([record]));
		await sync.load(privateSource);
		expect(objects.size).toBe(2);
		expect(objects.get(record.id)?.id).toBe(record.id);
		expect(objects.get(adapter.replyObjectId(record.id))?.inReplyToId).toBe(record.id);

		request.mockResolvedValueOnce({ ok: true }).mockResolvedValueOnce({ ...record, version: 3 });
		objects.delete(object.id);
		sync.handleEvent({ ...created, type: 'delete' } as AnnotationEvent);
		await sync.flush();
		objects.set(object.id, object);
		sync.handleEvent(created);
		await sync.flush();
		expect(request.mock.calls.at(-1)?.[2].params.path.annotation_id).toBe(record.id);
		expect(objects.has(record.id)).toBe(true);
		expect(objects.get(adapter.replyObjectId(record.id))?.inReplyToId).toBe(record.id);
	});

	it.each(['before', 'after'])(
		'loads server annotations once when native annotations finish %s the server load',
		async (order) => {
			const { sync, objects, statuses } = harness();
			const record = annotation('server-note');
			const native = adapter.vendorFromCanonical(
				canonicalAnnotationFromView(annotation('native-note'))
			);
			objects.set(native.id, native);
			request.mockResolvedValue(list([record]));
			const loaded: AnnotationEvent = { type: 'loaded', documentId: 'revision-1', total: 1 };
			if (order === 'before') sync.handleEvent(loaded);
			await sync.load(privateSource);
			if (order === 'after') sync.handleEvent(loaded);
			expect(request.mock.calls.filter(([method]) => method === 'GET')).toHaveLength(1);
			expect(objects.get(native.id)?.flags).toContain('readOnly');
			expect(objects.get(adapter.annotationObjectId(record.id))?.flags).not.toContain('readOnly');
			expect(statuses.at(-1)).toEqual({ state: 'loaded', count: 1 });
		}
	);

	it('displays the restored root and replies when Undo precedes the DELETE response', async () => {
		const { sync, objects, statuses, event } = harness();
		const record = annotation('deleted-root');
		record.replies = [reply(record)];
		let finishDelete!: (value: { ok: true }) => void;
		const pendingDelete = new Promise<{ ok: true }>((resolve) => {
			finishDelete = resolve;
		});
		request
			.mockResolvedValueOnce(list([record]))
			.mockReturnValueOnce(pendingDelete)
			.mockResolvedValueOnce({ ...record, version: 3 });
		await sync.load(privateSource);
		const deleting = event('delete', record);
		const undoing = event('create', record);
		expect(objects.has(adapter.annotationObjectId(record.id))).toBe(true); // EmbedPDF has already replayed Undo.
		finishDelete({ ok: true });
		await Promise.all([deleting, undoing]);
		expect(request.mock.calls[2]).toMatchObject([
			'POST',
			'/workspaces/{workspace_id}/items/{item_id}/annotations/{annotation_id}/restore',
			{ params: { query: { version: 2 } } }
		]);
		expect(objects.has(adapter.annotationObjectId(record.id))).toBe(true);
		expect(objects.get(adapter.replyObjectId('reply-1'))?.contents).toBe('Restored reply');
		expect(statuses.at(-1)).toEqual({ state: 'saved' });
		expect(request.mock.calls.filter(([method]) => method === 'GET')).toHaveLength(1);
	});

	it('restores a queued reply purged by a refresh during early Undo of its parent', async () => {
		const { sync, objects, event } = harness();
		const record = annotation('parent-with-queued-reply');
		const child = reply(record);
		record.replies = [child];
		let finishDelete!: (value: { ok: true }) => void;
		request
			.mockResolvedValueOnce(list([record]))
			.mockResolvedValueOnce({ ok: true }) // EmbedPDF deletes children before their parent.
			.mockReturnValueOnce(
				new Promise<{ ok: true }>((resolve) => {
					finishDelete = resolve;
				})
			)
			.mockResolvedValueOnce(list([{ ...record, replies: [] }]))
			.mockResolvedValueOnce({ ...record, version: 3, replies: [] })
			.mockResolvedValueOnce({ ...child, version: 3, body: 'Server-restored reply' });
		await sync.load(privateSource);
		await event('delete', record, child.id);
		const deleting = event('delete', record);
		const undoing = event('create', record);
		const undoingReply = event('create', record, child.id);
		await sync.load(privateSource);
		expect(objects.has(adapter.replyObjectId(child.id))).toBe(false);
		finishDelete({ ok: true });
		await Promise.all([deleting, undoing, undoingReply]);
		expect(objects.has(adapter.annotationObjectId(record.id))).toBe(true);
		expect(objects.get(adapter.replyObjectId(child.id))?.contents).toBe('Server-restored reply');
		expect(request.mock.calls[5]).toMatchObject([
			'POST',
			'/workspaces/{workspace_id}/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}/restore',
			{ params: { query: { version: 2 } } }
		]);
	});

	it('purges a deleted root reimported by a refresh while DELETE is pending', async () => {
		const { sync, objects, event } = harness();
		const record = annotation('deleted-during-refresh');
		let finishDelete!: (value: { ok: true }) => void;
		request
			.mockResolvedValueOnce(list([record]))
			.mockReturnValueOnce(
				new Promise<{ ok: true }>((resolve) => {
					finishDelete = resolve;
				})
			)
			.mockResolvedValueOnce(list([record]));
		await sync.load(privateSource);
		const deleting = event('delete', record);
		await sync.load(privateSource);
		expect(objects.has(adapter.annotationObjectId(record.id))).toBe(true);
		finishDelete({ ok: true });
		await deleting;
		expect(objects.has(adapter.annotationObjectId(record.id))).toBe(false);
	});

	it('keeps an early Undo hidden if its source is unselected before restore completes', async () => {
		const { sync, objects, event } = harness();
		const record = annotation('hidden-restore');
		let finishDelete!: (value: { ok: true }) => void;
		request
			.mockResolvedValueOnce(list([record]))
			.mockReturnValueOnce(
				new Promise<{ ok: true }>((resolve) => {
					finishDelete = resolve;
				})
			)
			.mockResolvedValueOnce(list([]))
			.mockResolvedValueOnce({ ...record, version: 3 });
		await sync.load(privateSource);
		const deleting = event('delete', record);
		const undoing = event('create', record);
		await sync.load(projectSource);
		finishDelete({ ok: true });
		await Promise.all([deleting, undoing]);
		expect(objects.size).toBe(0);
		expect(request.mock.calls.at(-1)?.[1]).toContain('/restore');
	});

	it('follows next_cursor even when the collection total changes between pages', async () => {
		const { sync, objects, statuses } = harness();
		const rows = Array.from({ length: 101 }, (_, i) =>
			annotation(`id-${String(i).padStart(3, '0')}`)
		);
		request
			.mockResolvedValueOnce(list(rows.slice(0, 100), rows[99].id, 101))
			.mockResolvedValueOnce(list(rows.slice(100), null, 100));
		await sync.load(privateSource);
		expect(objects.size).toBe(101);
		expect(objects.has(adapter.annotationObjectId('id-100'))).toBe(true);
		expect(request.mock.calls[1][2].params.query).toMatchObject({
			pagination: 'cursor',
			cursor: 'id-099'
		});
		expect(statuses.at(-1)).toEqual({ state: 'loaded', count: 101 });
	});

	it('invalidates externally deleted records before Undo and Redo can recreate a ghost', async () => {
		const { sync, objects, event } = harness();
		const record = annotation('created-here');
		request.mockResolvedValueOnce(list([])).mockResolvedValueOnce(record);
		await sync.load(privateSource);
		await event('create', record);
		expect(objects.has(adapter.annotationObjectId(record.id))).toBe(true);
		request.mockResolvedValueOnce(list([]));
		await sync.load(privateSource); // Another session deleted the record.
		expect(objects.size).toBe(0);
		await event('delete', record); // Undo the local creation; no live record remains.
		request
			.mockRejectedValueOnce(new Error('Annotation UUID remains reserved'))
			.mockResolvedValueOnce(list([]));
		await event('create', record); // Redo must consult the backend and purge its rejected object.
		expect(request.mock.calls.filter(([method]) => method === 'POST')).toHaveLength(2);
		expect(objects.size).toBe(0);
	});

	it('restarts a source refresh if a local creation finishes while its pages are in flight', async () => {
		const { sync, objects, event } = harness();
		const record = annotation('saved-during-refresh');
		let finishRead!: (value: ReturnType<typeof list>) => void;
		const pendingRead = new Promise<ReturnType<typeof list>>((resolve) => {
			finishRead = resolve;
		});
		request
			.mockReturnValueOnce(pendingRead)
			.mockResolvedValueOnce(record)
			.mockResolvedValueOnce(list([record]));
		const loading = sync.load(privateSource);
		await event('create', record);
		finishRead(list([])); // This collection was read before the creation committed.
		await loading;
		expect(objects.has(adapter.annotationObjectId(record.id))).toBe(true);
		expect(request.mock.calls.filter(([method]) => method === 'GET')).toHaveLength(2);
		await event('create', record);
		expect(request.mock.calls.filter(([method]) => method === 'POST')).toHaveLength(1);
	});

	it('retains hidden-source history but purges replayed objects outside the displayed sources', async () => {
		const { sync, objects, event } = harness();
		const record = annotation('hidden-private');
		request.mockResolvedValueOnce(list([record])).mockResolvedValueOnce(list([]));
		await sync.load(privateSource);
		await sync.load(projectSource);
		await event('create', record);
		expect(request).toHaveBeenCalledTimes(2);
		expect(objects.size).toBe(0);
		// An ordinary deletion still uses the retained version when history addresses that source.
		request.mockResolvedValueOnce({ ok: true });
		await event('delete', record);
		expect(request.mock.calls[2][0]).toBe('DELETE');
		expect(request.mock.calls[2][2].params.query).toEqual({ version: 1 });
	});
});
