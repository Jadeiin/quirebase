import { PdfAnnotationSubtype } from '@embedpdf/models';
import type {
	AnnotationCapability,
	AnnotationEvent,
	PdfAnnotationObject
} from '@embedpdf/svelte-pdf-viewer';
import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import { createWorkspaceApi } from '#lib/api/client.js';
import {
	canonicalAnnotationFromView,
	createAnnotationAdapter,
	type CanonicalAnnotation,
	type CanonicalReply
} from '#lib/pdf/annotation-adapter.js';
import {
	createWriteQueue,
	createAnnotationReplyApi,
	persistReplyEvent,
	selectNativeAnnotationIds
} from '#lib/pdf/annotation-writes.js';

export type AnnotationSyncStatus =
	| { state: 'loading' }
	| { state: 'loaded'; count: number }
	| { state: 'saving-reply' }
	| { state: 'saving-annotation' }
	| { state: 'saved' }
	| { state: 'sync-failed' }
	| { state: 'load-failed' };

type WritableAnnotationEvent = Exclude<AnnotationEvent, { type: 'loaded' }>;

export type AnnotationSources = {
	includePrivate: boolean;
	projectIds: string[];
};

export type AnnotationSyncOptions = {
	workspaceId: string;
	itemId: string;
	documentId: string;
	pageGeometry: number[][];
	initialSources: AnnotationSources;
	initialWriteProject: string;
	onStatus: (status: AnnotationSyncStatus) => void;
	onCommentPanel?: () => void;
};

export function createAnnotationSync(options: AnnotationSyncOptions) {
	const adapter = createAnnotationAdapter(options.pageGeometry);
	const workspaceApi = createWorkspaceApi(options.workspaceId);
	const writeQueue = createWriteQueue();
	// History can address a source after its overlay has been hidden. Retain the
	// canonical versions; importedIds tracks only objects displayed in EmbedPDF.
	const records = new SvelteMap<string, CanonicalAnnotation>();
	const importedIds = new SvelteMap<string, number>();
	// Keep deletion versions for the lifetime of EmbedPDF's history, across scope reloads.
	const tombstones = new SvelteMap<string, CanonicalAnnotation>();
	const replyTombstones = new SvelteMap<string, CanonicalReply>();
	const nativeIds = new SvelteSet<string>();
	let annotationApi: AnnotationCapability | null = null;
	let currentSources = options.initialSources;
	let writeProject = options.initialWriteProject;
	let loadGeneration = 0;
	let writeGeneration = 0;

	async function load(sources: AnnotationSources): Promise<void> {
		const api = annotationApi;
		if (!api) return;
		currentSources = sources;
		const generation = ++loadGeneration;
		const writesAtStart = writeGeneration;
		options.onStatus({ state: 'loading' });
		const rows: CanonicalAnnotation[] = [];
		if (sources.includePrivate || sources.projectIds.length) {
			let cursor: string | undefined;
			for (;;) {
				const result = await workspaceApi.request(
					'GET',
					'/workspaces/{workspace_id}/items/{item_id}/annotations',
					{
						params: {
							path: { item_id: options.itemId },
							query: {
								revision_id: options.documentId,
								scope: !sources.includePrivate
									? 'project'
									: !sources.projectIds.length
										? 'private'
										: undefined,
								project_id: sources.projectIds.length ? sources.projectIds : undefined,
								pagination: 'cursor',
								cursor,
								per_page: 100
							}
						}
					}
				);
				if (generation !== loadGeneration) return;
				rows.push(...result.annotations.map(canonicalAnnotationFromView));
				if (!result.next_cursor) break;
				cursor = result.next_cursor;
			}
		}
		if (generation !== loadGeneration) return;
		// A local write can finish while pages are in flight. Read again before
		// invalidating cache entries using a collection predating that write.
		if (writesAtStart !== writeGeneration) return load(currentSources);
		const refreshedIds = new SvelteSet(rows.map((record) => record.id));
		// Missing records in a fully refreshed source are no longer canonical.
		// Other sources remain cached so history can still address hidden overlays.
		for (const [id, record] of records) {
			if (inSources(record, sources) && !refreshedIds.has(id)) records.delete(id);
		}
		const scope = api.forDocument(options.documentId);
		for (const [id, pageIndex] of importedIds) scope.purgeAnnotation(pageIndex, id);
		importedIds.clear();
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

	function inSources(record: CanonicalAnnotation, sources: AnnotationSources) {
		return record.scope === 'private'
			? sources.includePrivate
			: sources.projectIds.includes(record.project_id ?? '');
	}

	function displayed(record: CanonicalAnnotation) {
		return inSources(record, currentSources);
	}

	function importMissingAnnotations(
		scope: ReturnType<AnnotationCapability['forDocument']>,
		objects: PdfAnnotationObject[]
	) {
		const missing = objects.filter((object) => !scope.getAnnotationById(object.id));
		if (missing.length) scope.importAnnotations(missing.map((annotation) => ({ annotation })));
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
					api: createAnnotationReplyApi(options.workspaceId),
					records,
					tombstones: replyTombstones
				});
				if (result) writeGeneration += 1;
				if (result?.reply) {
					if (displayed(result.parent)) {
						importedIds.set(result.reply.id, result.parent.page_index);
						scope.syncAnnotationObject(
							result.reply.id,
							adapter.vendorReplyFromCanonical(result.parent, result.reply)
						);
						if (event.type === 'create')
							importMissingAnnotations(scope, [
								adapter.vendorReplyFromCanonical(result.parent, result.reply)
							]);
					} else scope.purgeAnnotation(result.parent.page_index, result.reply.id);
				} else if (!result && event.type === 'create') scope.purgeAnnotation(event.pageIndex, id);
			} else if (event.type === 'create') {
				const existing = records.get(id);
				if (existing) {
					if (displayed(existing))
						scope.syncAnnotationObject(id, adapter.vendorFromCanonical(existing));
					else scope.purgeAnnotation(event.pageIndex, id);
					return;
				}
				options.onStatus({ state: 'saving-annotation' });
				const tombstone = tombstones.get(id);
				const savedView = tombstone
					? await workspaceApi.request(
							'POST',
							'/workspaces/{workspace_id}/items/{item_id}/annotations/{annotation_id}/restore',
							{
								params: {
									path: { item_id: options.itemId, annotation_id: id },
									query: { version: tombstone.version }
								}
							}
						)
					: await workspaceApi.request(
							'POST',
							'/workspaces/{workspace_id}/items/{item_id}/annotations',
							{
								params: { path: { item_id: options.itemId } },
								body: {
									id,
									revision_id: options.documentId,
									scope: scopeProject ? 'project' : 'private',
									project_id: scopeProject || null,
									...adapter.canonicalFromVendor(event.annotation, event.pageIndex)
								}
							}
						);
				const saved = canonicalAnnotationFromView(savedView);
				tombstones.delete(id);
				records.set(id, saved);
				writeGeneration += 1;
				if (displayed(saved)) {
					importedIds.set(id, saved.page_index);
					if (tombstone) {
						// DELETE may have purged objects already recreated by an early Undo.
						// Import without adding history entries or overwriting later edits.
						for (const reply of saved.replies) importedIds.set(reply.id, saved.page_index);
						importMissingAnnotations(scope, [
							adapter.vendorFromCanonical(saved),
							...saved.replies.map((reply) => adapter.vendorReplyFromCanonical(saved, reply))
						]);
					}
				} else scope.purgeAnnotation(saved.page_index, id);
			} else if (event.type === 'update') {
				const existing = records.get(id);
				if (!existing) return;
				options.onStatus({ state: 'saving-annotation' });
				const saved = canonicalAnnotationFromView(
					await workspaceApi.request(
						'PATCH',
						'/workspaces/{workspace_id}/items/{item_id}/annotations/{annotation_id}',
						{
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
						}
					)
				);
				records.set(id, saved);
				writeGeneration += 1;
				scope.syncAnnotationObject(id, adapter.vendorFromCanonical(saved));
			} else {
				const existing = records.get(id);
				if (!existing) return;
				options.onStatus({ state: 'saving-annotation' });
				await workspaceApi.request(
					'DELETE',
					'/workspaces/{workspace_id}/items/{item_id}/annotations/{annotation_id}',
					{
						params: {
							path: { item_id: options.itemId, annotation_id: id },
							query: { version: existing.version }
						}
					}
				);
				tombstones.set(id, { ...existing, version: existing.version + 1 });
				records.delete(id);
				importedIds.delete(id);
				writeGeneration += 1;
				// A source load may have reimported this object while DELETE was pending.
				for (const reply of existing.replies) {
					importedIds.delete(reply.id);
					scope.purgeAnnotation(existing.page_index, reply.id);
				}
				scope.purgeAnnotation(existing.page_index, id);
			}
			options.onStatus({ state: 'saved' });
		} catch {
			if (event.type === 'create') scope.purgeAnnotation(event.pageIndex, id);
			options.onStatus({ state: 'sync-failed' });
			await load(currentSources).catch(() => undefined);
		}
	}

	function handleEvent(event: AnnotationEvent) {
		if (!annotationApi || event.documentId !== options.documentId) return;
		if (event.type === 'loaded') {
			// EmbedPDF drains queued imports before this event. Viewer setup loads
			// server annotations; the native load only needs to lock PDF annotations.
			lockNative();
			return;
		}
		if (nativeIds.has(event.annotation.id)) return;
		if (event.type === 'create' && event.annotation.type === PdfAnnotationSubtype.TEXT) {
			options.onCommentPanel?.();
		}
		// Capture the scope at event time so a queued create is not retargeted by a
		// destination change that happens while it waits for earlier writes.
		const scopeProject = writeProject;
		void writeQueue.enqueue(() => persist(event, scopeProject));
	}

	return {
		attach(api: AnnotationCapability) {
			annotationApi = api;
		},
		load,
		lockNative,
		handleEvent,
		setWriteProject(projectId: string) {
			writeProject = projectId;
		},
		switchSources(sources: AnnotationSources) {
			currentSources = sources;
			const generation = ++loadGeneration;
			void (async () => {
				await writeQueue.flush().catch(() => undefined);
				if (generation !== loadGeneration) return;
				await load(sources).catch(() => options.onStatus({ state: 'load-failed' }));
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
