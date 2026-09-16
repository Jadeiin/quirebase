<script lang="ts">
	import type { AnnotationEvent } from '@embedpdf/plugin-annotation';
	import type { PdfAnnotationObject } from '@embedpdf/models';
	import { useAnnotation, useAnnotationCapability } from '@embedpdf/plugin-annotation/svelte';
	import { untrack } from 'svelte';
	import { SvelteMap, SvelteSet, SvelteURLSearchParams } from 'svelte/reactivity';
	import { apiRequest } from '$lib/api/client';
	import { msg, t } from '$lib/i18n';
	import {
		createAnnotationAdapter,
		type CanonicalAnnotation,
		type CanonicalReply
	} from '$lib/pdf/annotation-adapter';
	import {
		createWriteQueue,
		persistReplyEvent,
		selectNativeAnnotationIds
	} from '$lib/pdf/annotation-writes';

	let { itemId, documentId, editable, pageGeometry, projects } = $props<{
		itemId: string;
		documentId: string;
		editable: boolean;
		pageGeometry: number[][];
		projects: Array<{ id: string; name: string }>;
	}>();

	const annotations = useAnnotation(() => documentId);
	const annotationCapability = useAnnotationCapability();
	const adapter = $derived(createAnnotationAdapter(pageGeometry));
	const records = new SvelteMap<string, CanonicalAnnotation>();
	const importedIds = new SvelteMap<string, number>();
	const tombstones = new SvelteMap<string, CanonicalAnnotation>();
	const replyTombstones = new SvelteMap<string, CanonicalReply>();
	const nativeIds = new SvelteSet<string>();
	let selectedProject = $state('');
	let status = $state($t('Loading annotations…'));
	let syncFailed = $state(false);
	let annotationColor = $state('#ffcd45');
	let annotationOpacity = $state(1);
	let annotationStrokeWidth = $state(3);
	let loadGeneration = 0;
	const writeQueue = createWriteQueue();

	const tools = [
		['highlight', msg('Highlight')],
		['underline', msg('Underline')],
		['strikeout', msg('Strike out')],
		['textComment', msg('Note')],
		['ink', msg('Ink')],
		['square', msg('Rectangle')],
		['circle', msg('Ellipse')],
		['line', msg('Line')],
		['lineArrow', msg('Arrow')],
		['freeText', msg('Text')]
	] as const;

	function selectTool(toolId: string, active: boolean) {
		if (active) {
			annotations.provides?.setActiveTool(null);
			return;
		}
		const defaults = annotationCapability.provides?.getTool(toolId)?.defaults as
			Record<string, unknown> | undefined;
		annotationColor = String(defaults?.strokeColor ?? defaults?.color ?? annotationColor);
		annotationOpacity = Number(defaults?.opacity ?? annotationOpacity);
		annotationStrokeWidth = Number(defaults?.strokeWidth ?? annotationStrokeWidth);
		annotations.provides?.setActiveTool(toolId);
	}

	function applyAnnotationStyle() {
		const patch = {
			strokeColor: annotationColor,
			color: annotationColor,
			opacity: annotationOpacity,
			strokeWidth: annotationStrokeWidth
		};
		if (annotations.state.activeToolId) {
			annotationCapability.provides?.setToolDefaults(annotations.state.activeToolId, patch);
		}
		const selected = annotations.provides?.getSelectedAnnotations() ?? [];
		if (selected.length) {
			annotations.provides?.updateAnnotations(
				selected.map((tracked) => ({
					pageIndex: tracked.object.pageIndex,
					id: tracked.object.id,
					patch
				}))
			);
		}
	}

	function lockNativeAnnotations() {
		const api = annotations.provides;
		if (!api) return;
		const trackedById = new Map(
			api.getAnnotations().map((tracked) => [tracked.object.id, tracked] as const)
		);
		for (const id of selectNativeAnnotationIds(trackedById.keys(), importedIds)) {
			const tracked = trackedById.get(id)!;
			nativeIds.add(id);
			api.syncAnnotationObject(id, {
				flags: [...new Set([...(tracked.object.flags ?? []), 'readOnly' as const])]
			});
		}
	}

	async function loadAnnotations() {
		const api = annotations.provides;
		if (!api) return;
		const generation = ++loadGeneration;
		const requestedDocumentId = documentId;
		const requestedItemId = itemId;
		const requestedProject = selectedProject;
		status = $t('Loading annotations…');
		syncFailed = false;
		const query = new SvelteURLSearchParams({ revision_id: requestedDocumentId });
		if (requestedProject) query.set('project_id', requestedProject);
		let rows: CanonicalAnnotation[];
		try {
			rows = await apiRequest<CanonicalAnnotation[]>(
				`/items/${requestedItemId}/annotations?${query.toString()}`
			);
		} catch (reason) {
			if (generation !== loadGeneration) return;
			throw reason;
		}
		if (generation !== loadGeneration) return;
		for (const [id, pageIndex] of importedIds) api.purgeAnnotation(pageIndex, id);
		importedIds.clear();
		records.clear();
		replyTombstones.clear();
		for (const record of rows) {
			records.set(record.id, record);
			importedIds.set(record.id, record.page_index);
			for (const reply of record.replies) importedIds.set(reply.id, record.page_index);
		}
		api.importAnnotations(
			rows.flatMap((record) => [
				{ annotation: adapter.vendorFromCanonical(record) },
				...record.replies.map((reply) => ({
					annotation: adapter.vendorReplyFromCanonical(record, reply)
				}))
			])
		);
		status = `${rows.length} ${$t('annotations loaded')}`;
		syncFailed = false;
	}

	async function persist(event: Exclude<AnnotationEvent, { type: 'loaded' }>) {
		const api = annotations.provides;
		if (!api || event.documentId !== documentId || nativeIds.has(event.annotation.id)) return;
		const id = event.annotation.id;
		try {
			if (event.annotation.inReplyToId) {
				status = $t('Saving reply…');
				const result = await persistReplyEvent({
					event,
					itemId,
					records,
					tombstones: replyTombstones,
					request: apiRequest
				});
				if (result?.reply) {
					api.syncAnnotationObject(
						result.reply.id,
						adapter.vendorReplyFromCanonical(result.parent, result.reply)
					);
				}
			} else if (event.type === 'create') {
				if (records.has(id)) return;
				status = $t('Saving annotation…');
				const tombstone = tombstones.get(id);
				const saved = tombstone
					? await apiRequest<CanonicalAnnotation>(
							`/items/${itemId}/annotations/${id}/restore?version=${tombstone.version}`,
							{ method: 'POST' }
						)
					: await apiRequest<CanonicalAnnotation>(`/items/${itemId}/annotations`, {
							method: 'POST',
							body: {
								id,
								revision_id: documentId,
								scope: selectedProject ? 'project' : 'private',
								project_id: selectedProject || null,
								...adapter.canonicalFromVendor(event.annotation, event.pageIndex)
							}
						});
				tombstones.delete(id);
				records.set(id, saved);
				importedIds.set(id, saved.page_index);
			} else if (event.type === 'update') {
				const existing = records.get(id);
				if (!existing) return;
				status = $t('Saving annotation…');
				const saved = await apiRequest<CanonicalAnnotation>(`/items/${itemId}/annotations/${id}`, {
					method: 'PATCH',
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
				});
				records.set(id, saved);
				api.syncAnnotationObject(id, adapter.vendorFromCanonical(saved));
			} else {
				const existing = records.get(id);
				if (!existing) return;
				status = $t('Saving annotation…');
				await apiRequest(`/items/${itemId}/annotations/${id}?version=${existing.version}`, {
					method: 'DELETE'
				});
				tombstones.set(id, { ...existing, version: existing.version + 1 });
				records.delete(id);
				importedIds.delete(id);
			}
			status = $t('Saved');
			syncFailed = false;
		} catch {
			if (event.type === 'create') api.purgeAnnotation(event.pageIndex, id);
			status = $t('Annotation sync failed');
			syncFailed = true;
			await loadAnnotations().catch(() => undefined);
		}
	}

	async function changeProject() {
		await writeQueue.flush().catch(() => undefined);
		await loadAnnotations().catch(() => {
			status = $t('Unable to load annotations');
			syncFailed = true;
		});
	}

	$effect(() => {
		const api = annotations.provides;
		const activeDocumentId = documentId;
		if (!api) return;
		lockNativeAnnotations();
		void untrack(loadAnnotations).catch(() => {
			status = $t('Unable to load annotations');
			syncFailed = true;
		});
		const unsubscribe = api.onAnnotationEvent((event) => {
			if (event.type === 'loaded') {
				if (event.documentId !== activeDocumentId) return;
				lockNativeAnnotations();
				void untrack(loadAnnotations).catch(() => {
					status = $t('Unable to load annotations');
					syncFailed = true;
				});
				return;
			}
			void writeQueue.enqueue(() => persist(event));
		});
		const guardPendingWrites = (event: BeforeUnloadEvent) => {
			if (!writeQueue.hasPending()) return;
			event.preventDefault();
			event.returnValue = '';
		};
		const refreshFromInspector = () => {
			void writeQueue.flush().then(loadAnnotations);
		};
		window.addEventListener('beforeunload', guardPendingWrites);
		window.addEventListener('quirebase:annotations-changed', refreshFromInspector);
		return () => {
			loadGeneration += 1;
			unsubscribe();
			window.removeEventListener('beforeunload', guardPendingWrites);
			window.removeEventListener('quirebase:annotations-changed', refreshFromInspector);
		};
	});
</script>

<div
	class="flex items-center gap-1.5 overflow-x-auto border-b border-surface-300 bg-[#f9fbfa] px-2.5 py-1.5"
	aria-label={$t('Annotation tools')}
>
	<div class="flex shrink-0 items-center gap-1">
		{#if editable}
			{#each tools as [id, label] (id)}
				{@const active = annotations.state.activeToolId === id}
				<button
					class={`min-h-8 cursor-pointer rounded-md border px-2.5 py-1 text-xs font-medium whitespace-nowrap transition-colors ${active ? 'border-primary-700 bg-primary-700 text-white' : 'border-surface-300 bg-surface-100 text-surface-900 hover:border-primary-700/50 hover:bg-primary-50 hover:text-primary-800'}`}
					aria-pressed={active}
					onclick={() => selectTool(id, active)}>{$t(label)}</button
				>
			{/each}
		{/if}
	</div>
	{#if editable}
		<div class="flex shrink-0 items-center gap-2 border-l border-surface-300 pl-2">
			<label class="flex items-center gap-1 text-xs text-surface-600">
				<span class="sr-only">{$t('Annotation color')}</span>
				<input
					class="size-7 cursor-pointer rounded border border-surface-300 bg-transparent p-0.5"
					type="color"
					bind:value={annotationColor}
					onchange={applyAnnotationStyle}
				/>
			</label>
			<label class="flex items-center gap-1 text-xs text-surface-600">
				<span>{$t('Opacity')}</span><input
					class="accent-accent w-20"
					type="range"
					min="0.1"
					max="1"
					step="0.1"
					bind:value={annotationOpacity}
					onchange={applyAnnotationStyle}
				/>
			</label>
			<label class="flex items-center gap-1 text-xs text-surface-600">
				<span>{$t('Width')}</span><input
					class="accent-accent w-16"
					type="range"
					min="1"
					max="12"
					step="1"
					bind:value={annotationStrokeWidth}
					onchange={applyAnnotationStyle}
				/>
			</label>
		</div>
	{/if}
	<div class="ml-auto flex shrink-0 items-center gap-2 border-l border-surface-300 pl-2">
		<label>
			<span class="sr-only">{$t('Annotation visibility')}</span>
			<select
				class="min-h-8 max-w-48 rounded-md border border-surface-300 bg-surface-100 px-2 py-1 text-xs text-surface-900"
				bind:value={selectedProject}
				onchange={changeProject}
			>
				<option value="">{$t('Private annotations')}</option>
				{#each projects as project (project.id)}<option value={project.id}>{project.name}</option
					>{/each}
			</select>
		</label>
		<span class={`max-w-44 truncate text-xs ${syncFailed ? 'text-error-700' : 'text-surface-600'}`}
			>{status}</span
		>
	</div>
</div>
