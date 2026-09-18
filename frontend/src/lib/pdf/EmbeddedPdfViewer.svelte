<script lang="ts">
	import { onNavigate } from '$app/navigation';
	import { onDestroy } from 'svelte';
	import {
		AnnotationPlugin,
		CommandsPlugin,
		DocumentManagerPlugin,
		LockModeType,
		PDFViewer,
		UIPlugin,
		type AnnotationCapability,
		type PDFViewerConfig,
		type PluginRegistry,
		type UICapability
	} from '@embedpdf/svelte-pdf-viewer';
	import pdfiumWasmUrl from '@embedpdf/pdfium/pdfium.wasm?url';
	import { i18n } from '@lingui/core';
	import { apiErrorMessage } from '$lib/api/errors';
	import { t } from '$lib/i18n';
	import { createAnnotationSync, type AnnotationSyncStatus } from '$lib/pdf/annotation-sync.svelte';

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

	let registry: PluginRegistry | null = null;
	let annotationApi: AnnotationCapability | null = null;
	let uiApi: UICapability | null = null;
	let unsubscribeEvents: (() => void) | null = null;
	let destroyed = false;
	let cancelDocumentWait = () => {};
	// svelte-ignore state_referenced_locally
	const sync = createAnnotationSync({
		itemId,
		documentId,
		pageGeometry,
		initialProject: selectedProject,
		onStatus: reportStatus,
		onCommentPanel: () =>
			uiApi?.forDocument(documentId).setActiveSidebar('right', 'main', 'comment-panel')
	});

	function reportStatus(status: AnnotationSyncStatus) {
		if (!onstatus) return;
		switch (status.state) {
			case 'loading':
				onstatus($t('Loading annotations…'), false);
				break;
			case 'loaded':
				onstatus(`${status.count} ${$t('annotations loaded')}`, false);
				break;
			case 'saving-reply':
				onstatus($t('Saving reply…'), false);
				break;
			case 'saving-annotation':
				onstatus($t('Saving annotation…'), false);
				break;
			case 'saved':
				onstatus($t('Saved'), false);
				break;
			case 'sync-failed':
				onstatus($t('Annotation sync failed'), true);
				break;
			case 'load-failed':
				onstatus($t('Unable to load annotations'), true);
				break;
		}
	}

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
			sync.attach(annotationApi);
			unsubscribeEvents = annotationApi.onAnnotationEvent((event) => sync.handleEvent(event));
			await ready.pluginsReady();
			await waitForDocument();
			if (destroyed) return;
			if (!editable) annotationApi.setLocked({ type: LockModeType.All }, documentId);
			sync.lockNative();
			await sync.load(selectedProject).catch(() => {
				if (!destroyed) reportStatus({ state: 'load-failed' });
			});
		} catch (error) {
			if (destroyed) return;
			onstatus?.(apiErrorMessage(error, $t('Unable to open this PDF.')), true);
		}
	}

	$effect(() => {
		const guardPendingWrites = (event: BeforeUnloadEvent) => {
			if (!sync.hasPending()) return;
			event.preventDefault();
			event.returnValue = '';
		};
		window.addEventListener('beforeunload', guardPendingWrites);
		return () => {
			window.removeEventListener('beforeunload', guardPendingWrites);
		};
	});

	// Client-side navigation does not fire beforeunload. Keep the viewer mounted
	// until every queued annotation write has settled before SvelteKit tears it down.
	onNavigate(({ willUnload }) => {
		if (willUnload || !sync.hasPending()) return;
		return sync.flush().catch((reason) => {
			onstatus?.(apiErrorMessage(reason, $t('Annotation sync failed')), true);
			throw reason;
		});
	});

	let previousProject = selectedProject;
	$effect(() => {
		if (selectedProject === previousProject) return;
		previousProject = selectedProject;
		sync.switchProject(selectedProject);
	});

	onDestroy(() => {
		destroyed = true;
		cancelDocumentWait();
		sync.dispose();
		unsubscribeEvents?.();
		void registry?.destroy();
		registry = null;
	});
</script>

<div class="min-h-0 flex-1">
	<PDFViewer {config} onready={setup} class="h-full w-full" style="width:100%;height:100%" />
</div>
