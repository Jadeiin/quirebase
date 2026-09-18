<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		AnnotationPlugin,
		CommandsPlugin,
		DocumentManagerPlugin,
		LockModeType,
		PDFViewer,
		PdfAnnotationSubtype,
		UIPlugin,
		type AnnotationCapability,
		type AnnotationEvent,
		type PDFViewerConfig,
		type PdfAnnotationObject,
		type PluginRegistry,
		type UICapability
	} from '@embedpdf/svelte-pdf-viewer';
	import pdfiumWasmUrl from '@embedpdf/pdfium/pdfium.wasm?url';
	import { i18n } from '@lingui/core';
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import { t } from '$lib/i18n';
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

	let {
		itemId,
		documentId,
		name,
		url,
		editable,
		annotationAuthor,
		pageGeometry,
		selectedProject = $bindable(''),
		onstatus
	} = $props<{
		itemId: string;
		documentId: string;
		name: string;
		url: string;
		editable: boolean;
		annotationAuthor: string;
		pageGeometry: number[][];
		selectedProject?: string;
		onstatus?: (status: string, failed: boolean) => void;
	}>();

	const disabledCategories = [
		'document-open',
		'document-close',
		'document-print',
		'document-export',
		'document-protect',
		'document-capture',
		'form',
		'insert',
		'redaction',
		'stamp',
		'signature',
		'annotation-ink-highlighter',
		'annotation-insert-text',
		'annotation-link',
		'annotation-polygon',
		'annotation-polyline',
		'annotation-replace-text',
		'annotation-squiggly',
		'annotation-widget-edit',
		'annotation-group'
	];

	// svelte-ignore state_referenced_locally
	const config: PDFViewerConfig = {
		wasmUrl: pdfiumWasmUrl,
		fontFallback: null,
		fonts: { ui: null, signature: null },
		tabBar: 'never',
		disabledCategories,
		i18n: { defaultLocale: i18n.locale.startsWith('zh') ? 'zh-CN' : 'en' },
		documentManager: {
			initialDocuments: [{ url, documentId, name, requestOptions: { credentials: 'same-origin' } }]
		},
		annotations: {
			autoCommit: false,
			annotationAuthor,
			selectAfterCreate: true,
			editAfterCreate: true
		},
		permissions: {
			overrides: { print: false, copyContents: true, modifyAnnotations: editable }
		}
	};

	// svelte-ignore state_referenced_locally
	const adapter = createAnnotationAdapter(pageGeometry);
	const writeQueue = createWriteQueue();
	const records = new SvelteMap<string, CanonicalAnnotation>();
	const importedIds = new SvelteMap<string, number>();
	const tombstones = new SvelteMap<string, CanonicalAnnotation>();
	const replyTombstones = new SvelteMap<string, CanonicalReply>();
	const nativeIds = new SvelteSet<string>();
	let registry: PluginRegistry | null = null;
	let annotationApi: AnnotationCapability | null = null;
	let uiApi: UICapability | null = null;
	let unsubscribeEvents: (() => void) | null = null;
	let loadGeneration = 0;

	async function loadAnnotations() {
		if (!annotationApi) return;
		const generation = ++loadGeneration;
		const requestedProject = selectedProject;
		onstatus?.($t('Loading annotations…'), false);
		let rows: CanonicalAnnotation[];
		try {
			rows = (
				await apiRequest('GET', '/items/{item_id}/annotations', {
					params: {
						path: { item_id: itemId },
						query: {
							revision_id: documentId,
							project_id: requestedProject || undefined
						}
					}
				})
			).map(canonicalAnnotationFromView);
		} catch (reason) {
			if (generation !== loadGeneration) return;
			throw reason;
		}
		if (generation !== loadGeneration) return;
		const scope = annotationApi.forDocument(documentId);
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
		onstatus?.(`${rows.length} ${$t('annotations loaded')}`, false);
	}

	function lockNativeAnnotations() {
		if (!annotationApi) return;
		const scope = annotationApi.forDocument(documentId);
		const trackedById = new Map(
			scope.getAnnotations().map((tracked) => [tracked.object.id, tracked] as const)
		);
		for (const id of selectNativeAnnotationIds(trackedById.keys(), importedIds)) {
			const tracked = trackedById.get(id)!;
			nativeIds.add(id);
			scope.syncAnnotationObject(id, {
				flags: [...new Set([...(tracked.object.flags ?? []), 'readOnly' as const])]
			});
		}
	}

	async function persist(
		event: Exclude<AnnotationEvent, { type: 'loaded' }>,
		scopeProject: string
	) {
		if (!annotationApi || event.documentId !== documentId || nativeIds.has(event.annotation.id))
			return;
		const id = event.annotation.id;
		const scope = annotationApi.forDocument(documentId);
		try {
			if (event.annotation.inReplyToId) {
				onstatus?.($t('Saving reply…'), false);
				const result = await persistReplyEvent({
					event,
					itemId,
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
				onstatus?.($t('Saving annotation…'), false);
				const tombstone = tombstones.get(id);
				const savedView = tombstone
					? await apiRequest('POST', '/items/{item_id}/annotations/{annotation_id}/restore', {
							params: {
								path: { item_id: itemId, annotation_id: id },
								query: { version: tombstone.version }
							}
						})
					: await apiRequest('POST', '/items/{item_id}/annotations', {
							params: { path: { item_id: itemId } },
							body: {
								id,
								revision_id: documentId,
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
				onstatus?.($t('Saving annotation…'), false);
				const saved = canonicalAnnotationFromView(
					await apiRequest('PATCH', '/items/{item_id}/annotations/{annotation_id}', {
						params: { path: { item_id: itemId, annotation_id: id } },
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
				onstatus?.($t('Saving annotation…'), false);
				await apiRequest('DELETE', '/items/{item_id}/annotations/{annotation_id}', {
					params: {
						path: { item_id: itemId, annotation_id: id },
						query: { version: existing.version }
					}
				});
				tombstones.set(id, { ...existing, version: existing.version + 1 });
				records.delete(id);
				importedIds.delete(id);
			}
			onstatus?.($t('Saved'), false);
		} catch {
			if (event.type === 'create') scope.purgeAnnotation(event.pageIndex, id);
			onstatus?.($t('Annotation sync failed'), true);
			await loadAnnotations().catch(() => undefined);
		}
	}

	function handleAnnotationEvent(event: AnnotationEvent) {
		if (!annotationApi || event.documentId !== documentId) return;
		if (event.type === 'loaded') {
			lockNativeAnnotations();
			void loadAnnotations().catch(() => {
				onstatus?.($t('Unable to load annotations'), true);
			});
			return;
		}
		if (nativeIds.has(event.annotation.id)) return;
		if (event.type === 'create' && event.annotation.type === PdfAnnotationSubtype.TEXT) {
			uiApi?.forDocument(documentId).setActiveSidebar('right', 'main', 'comment-panel');
		}
		// Capture the scope at event time so a queued create is not retargeted by a
		// visibility change that happens while it waits for earlier writes.
		const scopeProject = selectedProject;
		void writeQueue.enqueue(() => persist(event, scopeProject));
	}

	let destroyed = false;
	let cancelDocumentWait = () => {};

	function waitForDocument() {
		const documentManager = registry?.getPlugin<DocumentManagerPlugin>(DocumentManagerPlugin.id);
		const api = documentManager?.provides();
		if (!api) return Promise.resolve();
		return new Promise<void>((resolve, reject) => {
			let settled = false;
			let timer: number | undefined;
			let unsubscribeOpened = () => {};
			let unsubscribeError = () => {};
			const finish = (callback: () => void) => {
				if (settled) return;
				settled = true;
				window.clearTimeout(timer);
				unsubscribeOpened();
				unsubscribeError();
				cancelDocumentWait = () => {};
				callback();
			};
			cancelDocumentWait = () => {
				finish(() => resolve());
			};
			unsubscribeOpened = api.onDocumentOpened((state) => {
				if (state.id === documentId) finish(resolve);
			});
			unsubscribeError = api.onDocumentError((event) => {
				if (event.documentId === documentId) finish(() => reject(new Error(event.message)));
			});
			const state = api.getDocumentState(documentId);
			if (state?.status === 'loaded') finish(resolve);
			if (state?.status === 'error')
				finish(() => reject(new Error(state.error ?? $t('Unable to open this PDF.'))));
			timer = window.setTimeout(
				() => finish(() => reject(new Error($t('Unable to open this PDF.')))),
				30_000
			);
		});
	}

	async function setup(ready: PluginRegistry) {
		try {
			registry = ready;
			annotationApi = ready.getPlugin<AnnotationPlugin>(AnnotationPlugin.id)?.provides() ?? null;
			uiApi = ready.getPlugin<UIPlugin>(UIPlugin.id)?.provides() ?? null;
			const commandsApi = ready.getPlugin<CommandsPlugin>(CommandsPlugin.id)?.provides() ?? null;
			commandsApi?.registerCommand({
				id: 'annotation:add-callout',
				action: () => {},
				visible: () => false,
				disabled: () => true
			});
			if (uiApi) {
				const schema = uiApi.getSchema();
				type SchemaItem = { id?: string; commandId?: string; items?: SchemaItem[] };
				const filterItems = <T extends SchemaItem>(items: T[]): T[] =>
					items
						.filter(
							(item) => item.id !== 'add-callout' && item.commandId !== 'annotation:add-callout'
						)
						.map((item) => {
							if (Array.isArray(item.items)) {
								return { ...item, items: filterItems(item.items) };
							}
							return item;
						});
				for (const toolbar of Object.values(schema.toolbars ?? {})) {
					toolbar.items = filterItems(toolbar.items);
				}
				for (const menu of Object.values(schema.menus ?? {})) {
					menu.items = filterItems(menu.items);
				}
			}
			if (!annotationApi) return;
			unsubscribeEvents = annotationApi.onAnnotationEvent(handleAnnotationEvent);
			await ready.pluginsReady();
			await waitForDocument();
			if (destroyed) return;
			if (!editable) annotationApi.setLocked({ type: LockModeType.All }, documentId);
			lockNativeAnnotations();
			await loadAnnotations().catch(() => {
				if (!destroyed) {
					onstatus?.($t('Unable to load annotations'), true);
				}
			});
		} catch (error) {
			if (destroyed) return;
			onstatus?.(apiErrorMessage(error, $t('Unable to open this PDF.')), true);
		}
	}

	$effect(() => {
		const guardPendingWrites = (event: BeforeUnloadEvent) => {
			if (!writeQueue.hasPending()) return;
			event.preventDefault();
			event.returnValue = '';
		};
		window.addEventListener('beforeunload', guardPendingWrites);
		return () => {
			window.removeEventListener('beforeunload', guardPendingWrites);
		};
	});

	let previousProject = selectedProject;
	$effect(() => {
		if (selectedProject === previousProject) return;
		previousProject = selectedProject;
		void (async () => {
			await writeQueue.flush().catch(() => undefined);
			await loadAnnotations().catch(() => {
				if (!destroyed) {
					onstatus?.($t('Unable to load annotations'), true);
				}
			});
		})();
	});

	onDestroy(() => {
		destroyed = true;
		cancelDocumentWait();
		loadGeneration += 1;
		unsubscribeEvents?.();
		void registry?.destroy();
		registry = null;
	});
</script>

<div class="min-h-0 flex-1">
	<PDFViewer {config} onready={setup} class="h-full w-full" style="width:100%;height:100%" />
</div>
