<script lang="ts">
	import { resolve } from '$app/paths';
	import { Dialog, Menu, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { apiRequest, type ItemSummary } from '$lib/api/client';
	import Icon from '$lib/design/Icon.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import RichText from '$lib/design/RichText.svelte';
	import { t } from '$lib/i18n';
	import HeadlessPdfViewer from '$lib/pdf/HeadlessPdfViewer.svelte';
	import type { CanonicalAnnotation, CanonicalReply } from '$lib/pdf/annotation-adapter';
	let { itemId, revisionId } = $props<{ itemId: string; revisionId: string }>();
	let inspectorOpen = $state(false);
	let exportProjectId = $state('');
	let inspectorBusy = $state(false);
	let inspectorError = $state('');
	const annotatedExportUrl = $derived(
		`/api/v1/items/${itemId}/revisions/${revisionId}/export?include_annotations=true${exportProjectId ? `&project_id=${encodeURIComponent(exportProjectId)}` : ''}`
	);
	type ViewerView = {
		item: ItemSummary;
		editable: boolean;
		annotation_author: string;
		revision: {
			id: string;
			original_name: string;
			page_count: number | null;
			processing_state: string;
			page_geometry: number[][];
			content_url: string;
		};
		projects: Array<{ id: string; name: string }>;
	};
	const viewer = createQuery(() => ({
		queryKey: ['pdf-viewer', itemId, revisionId],
		queryFn: () => apiRequest<ViewerView>(`/items/${itemId}/revisions/${revisionId}/viewer`)
	}));
	const annotations = createQuery(() => ({
		queryKey: ['pdf-inspector-annotations', itemId, revisionId],
		enabled: inspectorOpen,
		queryFn: () =>
			apiRequest<CanonicalAnnotation[]>(
				`/items/${itemId}/annotations?revision_id=${encodeURIComponent(revisionId)}`
			)
	}));

	async function inspectorMutation(operation: () => Promise<unknown>) {
		inspectorBusy = true;
		inspectorError = '';
		try {
			await operation();
			await annotations.refetch();
			window.dispatchEvent(new CustomEvent('quirebase:annotations-changed'));
			return true;
		} catch (reason) {
			inspectorError = reason instanceof Error ? reason.message : $t('Annotation action failed');
			return false;
		} finally {
			inspectorBusy = false;
		}
	}

	function updateAnnotation(event: SubmitEvent, annotation: CanonicalAnnotation) {
		event.preventDefault();
		const body = String(new FormData(event.currentTarget as HTMLFormElement).get('body') ?? '');
		void inspectorMutation(() =>
			apiRequest(`/items/${itemId}/annotations/${annotation.id}`, {
				method: 'PATCH',
				body: {
					version: annotation.version,
					page_index: annotation.page_index,
					kind: annotation.kind,
					scope: annotation.scope,
					project_id: annotation.project_id,
					body: body.trim() || null,
					selected_text: annotation.selected_text,
					payload: annotation.payload
				}
			})
		);
	}

	function deleteAnnotation(annotation: CanonicalAnnotation) {
		if (!window.confirm($t('Delete this Annotation?'))) return;
		void inspectorMutation(() =>
			apiRequest(`/items/${itemId}/annotations/${annotation.id}?version=${annotation.version}`, {
				method: 'DELETE'
			})
		);
	}

	function createReply(event: SubmitEvent, annotation: CanonicalAnnotation) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const body = String(new FormData(form).get('body') ?? '').trim();
		void inspectorMutation(() =>
			apiRequest(`/items/${itemId}/annotations/${annotation.id}/replies`, {
				method: 'POST',
				body: { id: crypto.randomUUID(), body }
			})
		).then((saved) => {
			if (saved) form.reset();
		});
	}

	function updateReply(event: SubmitEvent, annotation: CanonicalAnnotation, reply: CanonicalReply) {
		event.preventDefault();
		const body = String(
			new FormData(event.currentTarget as HTMLFormElement).get('body') ?? ''
		).trim();
		void inspectorMutation(() =>
			apiRequest(`/items/${itemId}/annotations/${annotation.id}/replies/${reply.id}`, {
				method: 'PATCH',
				body: { version: reply.version, body }
			})
		);
	}

	function deleteReply(annotation: CanonicalAnnotation, reply: CanonicalReply) {
		void inspectorMutation(() =>
			apiRequest(
				`/items/${itemId}/annotations/${annotation.id}/replies/${reply.id}?version=${reply.version}`,
				{ method: 'DELETE' }
			)
		);
	}
</script>

<div class="grid h-dvh min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden bg-[#dfe4e1]">
	<header class="flex items-center gap-3 border-b border-surface-300 bg-surface-50 px-3 py-2">
		<a
			class="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-surface-300 bg-surface-50 px-2.5 py-1.5 text-sm font-semibold text-surface-700 no-underline transition-colors hover:bg-surface-200 hover:text-primary-800"
			href={resolve('/(app)/item/[itemId]', { itemId })}
			><Icon name="chevron-left" /> <span>{$t('Item')}</span></a
		>
		<div class="grid min-w-0 flex-1">
			<strong class="truncate text-sm"
				><RichText html={viewer.data?.item.title_html ?? $t('PDF Reader')} /></strong
			><span class="truncate text-xs text-surface-600"
				>{viewer.data?.revision.original_name ?? $t('Loading')}</span
			>
		</div>
		<button
			class="hidden min-h-9 cursor-pointer items-center gap-1.5 rounded-md border border-surface-300 bg-surface-50 px-2.5 py-1.5 text-sm font-semibold text-surface-700 transition-colors hover:bg-surface-200 hover:text-primary-800 sm:inline-flex"
			onclick={() => (inspectorOpen = true)}
		>
			<Icon name="annotation" />
			{$t('Annotations')}
		</button>
		<Menu positioning={{ placement: 'bottom-end', gutter: 6 }}>
			<Menu.Trigger
				class="inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-md border border-surface-300 bg-surface-50 px-2.5 py-1.5 text-sm font-semibold text-surface-700 transition-colors hover:bg-surface-200 hover:text-primary-800"
			>
				<Icon name="download" /> <span class="hidden sm:inline">{$t('Download')}</span><Icon
					name="chevron-down"
					size={14}
				/>
			</Menu.Trigger>
			<Portal>
				<Menu.Positioner class="z-100">
					<Menu.Content
						class="w-[min(22rem,calc(100vw-1rem))] rounded-container border border-surface-300 bg-surface-50 p-1.5 shadow-xl"
					>
						<div class="px-2.5 py-2 text-xs font-bold tracking-wide text-surface-600 uppercase">
							{$t('Current PDF')}
						</div>
						<Menu.Item
							value="download-original"
							class="flex cursor-pointer items-center rounded-md text-sm outline-none data-[highlighted]:bg-primary-50 data-[highlighted]:text-primary-800"
						>
							<a
								class="w-full px-2.5 py-2 no-underline"
								href={`/api/v1/items/${itemId}/revisions/${revisionId}/content`}
								download={viewer.data?.revision.original_name ?? ''}
								rel="external"
								data-sveltekit-reload>{$t('Download original')}</a
							>
						</Menu.Item>
						<div class="m-1 h-px bg-surface-300"></div>
						<label class="grid gap-1.5 px-2.5 py-2 text-xs font-medium text-surface-700">
							{$t('Annotations to include')}
							<select
								class="min-h-9 rounded-md border border-surface-300 bg-surface-100 px-2 text-sm text-surface-900"
								bind:value={exportProjectId}
							>
								<option value="">{$t('Private annotations only')}</option>
								{#each viewer.data?.projects ?? [] as project (project.id)}
									<option value={project.id}
										>{$t('Private annotations and project')}: {project.name}</option
									>
								{/each}
							</select>
						</label>
						<Menu.Item
							value="download-annotated"
							class="flex cursor-pointer items-center rounded-md text-sm outline-none data-[highlighted]:bg-primary-50 data-[highlighted]:text-primary-800"
						>
							<a
								class="w-full px-2.5 py-2 no-underline"
								href={annotatedExportUrl}
								rel="external"
								data-sveltekit-reload>{$t('Download with annotations')}</a
							>
						</Menu.Item>
					</Menu.Content>
				</Menu.Positioner>
			</Portal>
		</Menu>
	</header>
	<div class="flex h-full min-h-0 flex-col overflow-hidden bg-[#dfe4e1]">
		{#if viewer.isPending}<div class="grid h-full place-items-center text-surface-600">
				{$t('Loading reader configuration…')}
			</div>
		{:else if viewer.isError}<div class="grid h-full place-items-center text-error-700">
				{$t('Unable to open this PDF.')}
			</div>
		{:else if viewer.data}<HeadlessPdfViewer
				{itemId}
				documentId={revisionId}
				name={viewer.data.revision.original_name}
				url={viewer.data.revision.content_url}
				editable={viewer.data.editable}
				annotationAuthor={viewer.data.annotation_author}
				pageGeometry={viewer.data.revision.page_geometry}
				projects={viewer.data.projects}
			/>{/if}
	</div>
	<Dialog open={inspectorOpen} onOpenChange={(details) => (inspectorOpen = details.open)}>
		<Dialog.Trigger
			class="flex w-full cursor-pointer items-center justify-between border-0 bg-primary-950 px-4 py-3 text-sm font-semibold text-white sm:hidden"
			><span class="flex items-center gap-2"><Icon name="annotation" /> {$t('Annotations')}</span
			><span class="flex items-center gap-1 text-surface-400"
				>{$t('Open inspector')} <Icon name="chevron-right" /></span
			></Dialog.Trigger
		>
		<Portal>
			<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
			<Dialog.Positioner
				class="fixed inset-0 z-71 flex items-end justify-center p-0 sm:items-end sm:justify-end sm:p-4"
			>
				<Dialog.Content
					class="grid max-h-[72dvh] w-full overflow-hidden rounded-t-2xl border border-surface-300 bg-surface-50 shadow-2xl sm:w-[min(27rem,calc(100vw-2rem))] sm:rounded-container"
				>
					<header class="flex items-center justify-between border-b border-surface-300 px-4 py-3">
						<Dialog.Title class="font-semibold">{$t('Annotation inspector')}</Dialog.Title>
						<Dialog.CloseTrigger class="btn-icon preset-tonal-surface" aria-label={$t('Close')}
							><Icon name="close" /></Dialog.CloseTrigger
						>
					</header>
					<div class="overflow-auto px-4 pt-2 pb-[calc(1rem+env(safe-area-inset-bottom))]">
						{#if inspectorError}<p class="text-error-700" role="alert">{inspectorError}</p>{/if}
						{#if annotations.isPending}<p class="text-surface-600">{$t('Loading annotations…')}</p>
						{:else if annotations.isError}<p class="text-error-700">
								{$t('Unable to load annotations.')}
							</p>
						{:else}{#each annotations.data ?? [] as annotation (annotation.id)}<article
									class="grid gap-3 border-b border-surface-300 py-4 last:border-0"
								>
									<div>
										<strong class="text-sm"
											>{$t(domainLabel(annotation.kind))} · {$t('page')}
											{annotation.page_index + 1}</strong
										>
										<p class="mb-0 text-xs text-surface-600">
											{annotation.author_display_name} · {annotation.scope}
										</p>
									</div>
									{#if annotation.selected_text}<blockquote
											class="m-0 border-l-2 border-primary-700 pl-2 text-sm text-surface-700"
										>
											{annotation.selected_text}
										</blockquote>{/if}
									{#if annotation.editable}<form
											class="stack"
											onsubmit={(event) => updateAnnotation(event, annotation)}
										>
											<textarea
												class="textarea min-h-20 text-sm"
												name="body"
												value={annotation.body ?? ''}></textarea>
											<div class="toolbar">
												<button
													class="btn preset-tonal-surface font-semibold"
													disabled={inspectorBusy}>{$t('Save note')}</button
												><button
													type="button"
													class="btn preset-tonal-error font-semibold"
													disabled={inspectorBusy}
													onclick={() => deleteAnnotation(annotation)}
													>{$t('Delete Annotation')}</button
												>
											</div>
										</form>{:else if annotation.body}<p class="mb-0 text-sm">
											{annotation.body}
										</p>{/if}
									<div class="rounded-lg bg-surface-200 p-2">
										<h4 class="mb-2 text-sm">{$t('Replies')}</h4>
										{#each annotation.replies as reply (reply.id)}{#if reply.editable}<form
													class="stack border-t border-surface-300 py-2 first:border-0"
													onsubmit={(event) => updateReply(event, annotation, reply)}
												>
													<small class="text-surface-600">{reply.author_display_name}</small
													><textarea
														class="textarea min-h-16 text-sm"
														name="body"
														value={reply.body}></textarea>
													<div class="toolbar">
														<button
															class="btn preset-tonal-surface font-semibold"
															disabled={inspectorBusy}>{$t('Save reply')}</button
														><button
															type="button"
															class="btn preset-tonal-error font-semibold"
															disabled={inspectorBusy}
															onclick={() => deleteReply(annotation, reply)}
															>{$t('Delete reply')}</button
														>
													</div>
												</form>{:else}<div class="border-t border-surface-300 py-2 first:border-0">
													<small class="text-surface-600">{reply.author_display_name}</small>
													<p class="mb-0 text-sm">{reply.body}</p>
												</div>{/if}{/each}
										<form
											class="toolbar border-t border-surface-300 pt-2"
											onsubmit={(event) => createReply(event, annotation)}
										>
											<input
												class="input grow"
												name="body"
												placeholder={$t('Write a reply')}
												required
											/><button
												class="btn preset-tonal-surface font-semibold"
												disabled={inspectorBusy}>{$t('Reply')}</button
											>
										</form>
									</div>
								</article>{:else}<p class="text-surface-600">{$t('No annotations.')}</p>{/each}{/if}
					</div>
				</Dialog.Content>
			</Dialog.Positioner>
		</Portal>
	</Dialog>
</div>
