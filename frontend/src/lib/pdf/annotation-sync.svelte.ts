import {
	PdfAnnotationSubtype,
	type AnnotationCapability,
	type AnnotationEvent,
	type PdfAnnotationObject
} from '@embedpdf/svelte-pdf-viewer';
import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import { apiRequest } from '$lib/api/client';
import {
	canonicalAnnotationFromView,
	createAnnotationAdapter,
	type CanonicalAnnotation,
	type CanonicalReply
} from '$lib/pdf/annotation-adapter';
import {
	createWriteQueue,
	persistReplyEvent,
	selectNativeAnnotationIds
} from '$lib/pdf/annotation-writes';

export type AnnotationSyncStatus =
	| { state: 'loading' }
	| { state: 'loaded'; count: number }
	| { state: 'saving-reply' }
	| { state: 'saving-annotation' }
	| { state: 'saved' }
	| { state: 'sync-failed' }
	| { state: 'load-failed' };

type WritableAnnotationEvent = Exclude<AnnotationEvent, { type: 'loaded' }>;

export type AnnotationSyncOptions = {
	itemId: string;
	documentId: string;
	pageGeometry: number[][];
	initialProject?: string;
	onStatus: (status: AnnotationSyncStatus) => void;
	onCommentPanel?: () => void;
};

export function createAnnotationSync(options: AnnotationSyncOptions) {
	const adapter = createAnnotationAdapter(options.pageGeometry);
	const writeQueue = createWriteQueue();
	const records = new SvelteMap<string, CanonicalAnnotation>();
	const importedIds = new SvelteMap<string, number>();
	const tombstones = new SvelteMap<string, CanonicalAnnotation>();
	const replyTombstones = new SvelteMap<string, CanonicalReply>();
	const nativeIds = new SvelteSet<string>();
	let annotationApi: AnnotationCapability | null = null;
	let currentProject = options.initialProject ?? '';
	let loadGeneration = 0;

	async function load(projectId: string) {
		const api = annotationApi;
		if (!api) return;
		currentProject = projectId;
		const generation = ++loadGeneration;
		options.onStatus({ state: 'loading' });
		const rows = (
			await apiRequest('GET', '/items/{item_id}/annotations', {
				params: {
					path: { item_id: options.itemId },
					query: {
						revision_id: options.documentId,
						project_id: projectId || undefined
					}
				}
			})
		).map(canonicalAnnotationFromView);
		if (generation !== loadGeneration) return;
		const scope = api.forDocument(options.documentId);
		for (const [id, pageIndex] of importedIds) scope.purgeAnnotation(pageIndex, id);
		importedIds.clear();
		records.clear();
		replyTombstones.clear();
		for (const record of rows) {
			records.set(record.id, record);
			importedIds.set(record.id, record.page_index);
			for (const reply of record.replies) importedIds.set(reply.id, record.page_index);
		}
		scope.importAnnotations(
			rows.flatMap((record) => [
				{ annotation: adapter.vendorFromCanonical(record) },
				...record.replies.map((reply) => ({
					annotation: adapter.vendorReplyFromCanonical(record, reply)
				}))
			])
		);
		options.onStatus({ state: 'loaded', count: rows.length });
	}

	function lockNative() {
		const api = annotationApi;
		if (!api) return;
		const scope = api.forDocument(options.documentId);
		const trackedById = new SvelteMap(
			scope.getAnnotations().map((tracked) => [tracked.object.id, tracked] as const)
		);
		for (const id of selectNativeAnnotationIds(trackedById.keys(), importedIds)) {
			const tracked = trackedById.get(id)!;
			nativeIds.add(id);
			scope.syncAnnotationObject(id, {
				flags: [...new SvelteSet([...(tracked.object.flags ?? []), 'readOnly' as const])]
			});
		}
	}

	async function persist(event: WritableAnnotationEvent, scopeProject: string) {
		const api = annotationApi;
		if (!api || event.documentId !== options.documentId || nativeIds.has(event.annotation.id))
			return;
		const id = event.annotation.id;
		const scope = api.forDocument(options.documentId);
		try {
			if (event.annotation.inReplyToId) {
				options.onStatus({ state: 'saving-reply' });
				const result = await persistReplyEvent({
					event,
					itemId: options.itemId,
					records,
					tombstones: replyTombstones
				});
				if (result?.reply) {
					scope.syncAnnotationObject(
						result.reply.id,
						adapter.vendorReplyFromCanonical(result.parent, result.reply)
					);
				}
			} else if (event.type === 'create') {
				if (records.has(id)) return;
				options.onStatus({ state: 'saving-annotation' });
				const tombstone = tombstones.get(id);
				const savedView = tombstone
					? await apiRequest('POST', '/items/{item_id}/annotations/{annotation_id}/restore', {
							params: {
								path: { item_id: options.itemId, annotation_id: id },
								query: { version: tombstone.version }
							}
						})
					: await apiRequest('POST', '/items/{item_id}/annotations', {
							params: { path: { item_id: options.itemId } },
							body: {
								id,
								revision_id: options.documentId,
								scope: scopeProject ? 'project' : 'private',
								project_id: scopeProject || null,
								...adapter.canonicalFromVendor(event.annotation, event.pageIndex)
							}
						});
				const saved = canonicalAnnotationFromView(savedView);
				tombstones.delete(id);
				records.set(id, saved);
				importedIds.set(id, saved.page_index);
			} else if (event.type === 'update') {
				const existing = records.get(id);
				if (!existing) return;
				options.onStatus({ state: 'saving-annotation' });
				const saved = canonicalAnnotationFromView(
					await apiRequest('PATCH', '/items/{item_id}/annotations/{annotation_id}', {
						params: { path: { item_id: options.itemId, annotation_id: id } },
						body: {
							version: existing.version,
							scope: existing.scope,
							project_id: existing.project_id,
							...adapter.canonicalFromVendor(
								{ ...event.annotation, ...event.patch } as PdfAnnotationObject,
								event.pageIndex,
								existing
							)
						}
					})
				);
				records.set(id, saved);
				scope.syncAnnotationObject(id, adapter.vendorFromCanonical(saved));
			} else {
				const existing = records.get(id);
				if (!existing) return;
				options.onStatus({ state: 'saving-annotation' });
				await apiRequest('DELETE', '/items/{item_id}/annotations/{annotation_id}', {
					params: {
						path: { item_id: options.itemId, annotation_id: id },
						query: { version: existing.version }
					}
				});
				tombstones.set(id, { ...existing, version: existing.version + 1 });
				records.delete(id);
				importedIds.delete(id);
			}
			options.onStatus({ state: 'saved' });
		} catch {
			if (event.type === 'create') scope.purgeAnnotation(event.pageIndex, id);
			options.onStatus({ state: 'sync-failed' });
			await load(currentProject).catch(() => undefined);
		}
	}

	function handleEvent(event: AnnotationEvent) {
		if (!annotationApi || event.documentId !== options.documentId) return;
		if (event.type === 'loaded') {
			lockNative();
			void load(currentProject).catch(() => options.onStatus({ state: 'load-failed' }));
			return;
		}
		if (nativeIds.has(event.annotation.id)) return;
		if (event.type === 'create' && event.annotation.type === PdfAnnotationSubtype.TEXT) {
			options.onCommentPanel?.();
		}
		// Capture the scope at event time so a queued create is not retargeted by a
		// visibility change that happens while it waits for earlier writes.
		const scopeProject = currentProject;
		void writeQueue.enqueue(() => persist(event, scopeProject));
	}

	return {
		attach(api: AnnotationCapability) {
			annotationApi = api;
		},
		load,
		lockNative,
		handleEvent,
		switchProject(projectId: string) {
			currentProject = projectId;
			void (async () => {
				await writeQueue.flush().catch(() => undefined);
				await load(projectId).catch(() => options.onStatus({ state: 'load-failed' }));
			})();
		},
		flush() {
			return writeQueue.flush();
		},
		hasPending() {
			return writeQueue.hasPending();
		},
		dispose() {
			annotationApi = null;
			loadGeneration += 1;
		}
	};
}

export type AnnotationSync = ReturnType<typeof createAnnotationSync>;
