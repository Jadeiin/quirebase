<script lang="ts">
	import { resolve } from '$app/paths';
	import { Menu, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import { apiRequest } from '$lib/api/client';
	import Icon from '$lib/design/Icon.svelte';
	import RichText from '$lib/design/RichText.svelte';
	import { t } from '$lib/i18n';
	import type { components } from '$lib/api/schema';
	import EmbeddedPdfViewer from '$lib/pdf/EmbeddedPdfViewer.svelte';

	let { itemId, revisionId } = $props<{ itemId: string; revisionId: string }>();
	let exportProjectId = $state('');
	let selectedProject = $state('');
	let annotationStatus = $state('');
	let annotationSyncFailed = $state(false);
	const annotatedExportUrl = $derived.by(() => {
		const parameters = new SvelteURLSearchParams({
			include_annotations: 'true',
			timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
		});
		if (exportProjectId) parameters.set('project_id', exportProjectId);
		return `/api/v1/items/${itemId}/revisions/${revisionId}/export?${parameters}`;
	});
	type ViewerView = components['schemas']['PdfViewerView'];
	const viewer = createQuery(() => ({
		queryKey: ['pdf-viewer', itemId, revisionId],
		queryFn: () => apiRequest<ViewerView>(`/items/${itemId}/revisions/${revisionId}/viewer`)
	}));
</script>

<div class="grid h-dvh min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden bg-[#dfe4e1]">
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
		{#if viewer.data}<label class="flex shrink-0 items-center">
				<span class="sr-only">{$t('Annotation visibility')}</span>
				<select
					class="min-h-9 max-w-32 rounded-md border border-surface-300 bg-surface-100 px-2 py-1 text-xs text-surface-900 sm:max-w-48"
					bind:value={selectedProject}
				>
					<option value="">{$t('Private annotations')}</option>
					{#each viewer.data.projects as project (project.id)}<option value={project.id}
							>{project.name}</option
						>{/each}
				</select>
			</label>{/if}
		<span
			class={`max-w-44 truncate text-xs ${annotationSyncFailed ? 'inline font-semibold text-error-700' : 'hidden text-surface-600 lg:inline'}`}
			>{annotationStatus}</span
		>
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
						class="z-1000 w-[min(22rem,calc(100vw-1rem))] rounded-container border border-surface-300 bg-surface-50 p-1.5 shadow-xl"
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
		{#if annotationSyncFailed && annotationStatus}
			<aside
				class="flex shrink-0 items-center justify-between gap-2 border-b border-error-300 bg-error-50 px-3 py-1.5 text-xs font-medium text-error-800"
				role="alert"
			>
				<span class="truncate">{annotationStatus}</span>
				<button
					type="button"
					class="cursor-pointer font-semibold text-error-800 hover:underline"
					onclick={() => {
						annotationSyncFailed = false;
					}}>{$t('Dismiss')}</button
				>
			</aside>
		{/if}
		{#if viewer.isPending}<div class="grid min-h-0 flex-1 place-items-center text-surface-600">
				{$t('Loading reader configuration…')}
			</div>
		{:else if viewer.isError}<div class="grid min-h-0 flex-1 place-items-center text-error-700">
				{$t('Unable to open this PDF.')}
			</div>
		{:else if viewer.data}{#key revisionId}<EmbeddedPdfViewer
					{itemId}
					documentId={revisionId}
					name={viewer.data.revision.original_name}
					url={viewer.data.revision.content_url}
					editable={viewer.data.editable}
					annotationAuthor={viewer.data.annotation_author}
					pageGeometry={viewer.data.revision.page_geometry}
					bind:selectedProject
					onstatus={(text, failed) => {
						annotationStatus = text;
						annotationSyncFailed = failed;
					}}
				/>{/key}{/if}
	</div>
</div>
