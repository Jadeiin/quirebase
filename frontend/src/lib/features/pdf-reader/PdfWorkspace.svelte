<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { Menu, Popover, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { ApiError, isDownloadCancelled } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Icon from '#lib/design/Icon.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import { pdfViewerQuery } from '#lib/features/pdf-reader/queries.js';
	import { t } from '#lib/i18n.js';
	import EmbeddedPdfViewer from '#lib/pdf/EmbeddedPdfViewer.svelte';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';

	let { itemId, revisionId } = $props<{ itemId: string; revisionId: string }>();
	const workspace = getWorkspaceContext();
	const { workspaceId } = workspace;
	let exportProjectId = $state('');
	let includePrivate = $state(true);
	let visibleProjects = $state(page.url.searchParams.getAll('project_id'));
	let writeProject = $state('');
	let annotationStatus = $state('');
	let annotationSyncFailed = $state(false);
	let downloadError = $state('');
	const viewer = createQuery(() => pdfViewerQuery(workspaceId, itemId, revisionId));
	const readableProjects = $derived(new Set(viewer.data?.projects.map((project) => project.id)));
	const sources = $derived({
		includePrivate,
		projectIds: visibleProjects.filter((id) => readableProjects.has(id))
	});
	$effect(() => {
		if (!viewer.data) return;
		const available = visibleProjects.filter((id) => readableProjects.has(id));
		if (available.length !== visibleProjects.length) visibleProjects = available;
		if (writeProject && !readableProjects.has(writeProject)) writeProject = '';
		if (exportProjectId && !readableProjects.has(exportProjectId)) exportProjectId = '';
	});
	const editable = $derived(
		writeProject
			? (viewer.data?.projects.find((project) => project.id === writeProject)?.editable ?? false)
			: (viewer.data?.editable ?? false)
	);

	function showProject(projectId: string, checked: boolean) {
		visibleProjects = checked
			? [...new Set([...visibleProjects, projectId])]
			: visibleProjects.filter((id) => id !== projectId);
	}

	function selectWriteProject(projectId: string) {
		if (projectId) showProject(projectId, true);
		else includePrivate = true;
	}

	async function download(operation: Promise<void>) {
		downloadError = '';
		try {
			await operation;
		} catch (reason) {
			if (isDownloadCancelled(reason)) return;
			downloadError = apiErrorMessage(reason, $t('Item action failed'));
		}
	}

	function downloadOriginal() {
		if (!viewer.data) return;
		void download(
			workspace.api.downloadGet(
				'/workspaces/{workspace_id}/items/{item_id}/revisions/{revision_id}/content',
				{
					params: { path: { item_id: itemId, revision_id: revisionId } }
				},
				{ suggestedName: viewer.data.revision.original_name }
			)
		);
	}

	function downloadAnnotated() {
		if (!viewer.data) return;
		const originalName = viewer.data.revision.original_name;
		void download(
			workspace.api.downloadGet(
				'/workspaces/{workspace_id}/items/{item_id}/revisions/{revision_id}/export',
				{
					params: {
						path: { item_id: itemId, revision_id: revisionId },
						query: {
							include_annotations: true,
							timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
							project_id: exportProjectId || undefined
						}
					}
				},
				{
					suggestedName: `${originalName.replace(/\.[^/.]+$/, '')}-annotated.pdf`
				}
			)
		);
	}
</script>

<div
	class="grid h-dvh min-h-0 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] overflow-hidden bg-surface-300-700"
>
	<header
		class="flex min-w-0 items-center gap-2 border-b border-surface-300-700 bg-surface-50-950 px-3 py-2 sm:gap-3"
	>
		<a
			class="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md border border-surface-300-700 bg-surface-50-950 px-2.5 py-1.5 text-sm font-semibold text-surface-700-300 no-underline transition-colors hover:bg-surface-200-800 hover:text-primary-800-200"
			aria-label={$t('Item')}
			href={resolve(workspaceHref(workspaceId, `item/${itemId}`))}
			><Icon name="chevron-left" /> <span class="hidden sm:inline">{$t('Item')}</span></a
		>
		<div class="grid min-w-0 flex-1 grid-cols-1">
			<strong class="truncate text-sm"
				><RichText html={viewer.data?.item.title_html ?? $t('PDF Reader')} /></strong
			><span class="truncate text-xs text-surface-600-400"
				>{viewer.data?.revision.original_name ?? $t('Loading')}</span
			>
		</div>

		<span
			class={`max-w-44 truncate text-xs ${annotationSyncFailed ? 'inline font-semibold text-error-700-300' : 'hidden text-surface-600-400 lg:inline'}`}
			>{annotationStatus}</span
		>
		{#if viewer.data}
			<Popover positioning={{ placement: 'bottom-end', gutter: 6 }}>
				<Popover.Trigger
					class="inline-flex min-h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-surface-300-700 bg-surface-50-950 px-2.5 py-1.5 text-sm font-semibold text-surface-700-300 transition-colors hover:bg-surface-200-800 hover:text-primary-800-200"
					aria-label={$t('Displayed annotation sources')}
					title={$t('Displayed annotation sources')}
				>
					<Icon name="annotation" />
					<span class="hidden md:inline">{$t('Annotations')}</span>
					<span class="hidden sm:inline-flex"><Icon name="chevron-down" size={14} /></span>
				</Popover.Trigger>
				<Portal>
					<Popover.Positioner class="z-100">
						<Popover.Content
							class="max-h-72 w-64 max-w-[calc(100vw-1.5rem)] overflow-y-auto rounded-md border border-surface-300-700 bg-surface-50-950 p-3 text-sm shadow-xl"
						>
							<Popover.Title class="mb-3 text-xs font-semibold text-surface-600-400"
								>{$t('Displayed annotation sources')}</Popover.Title
							>
							<div class="grid grid-cols-1 gap-2">
								<label class="flex min-w-0 items-center gap-2"
									><input type="checkbox" bind:checked={includePrivate} />{$t(
										'Private annotations'
									)}</label
								>
								{#each viewer.data.projects as project (project.id)}
									<label class="flex min-w-0 items-center gap-2"
										><input
											type="checkbox"
											checked={visibleProjects.includes(project.id)}
											onchange={(event) => showProject(project.id, event.currentTarget.checked)}
										/><span class="min-w-0 wrap-break-word">{project.name}</span></label
									>
								{/each}
							</div>
						</Popover.Content>
					</Popover.Positioner>
				</Portal>
			</Popover>
			<label class="min-w-0 shrink-0">
				<span class="sr-only">{$t('New annotation source')}</span>
				<select
					class="min-h-9 w-28 truncate rounded-md border border-surface-300-700 bg-surface-100-900 px-2 py-1 text-xs text-surface-900-100 sm:w-40"
					title={$t('New annotation source')}
					bind:value={writeProject}
					onchange={(event) => selectWriteProject(event.currentTarget.value)}
				>
					<option value="" disabled={!viewer.data.editable}>{$t('Private annotations')}</option>
					{#each viewer.data.projects as project (project.id)}<option
							value={project.id}
							disabled={!project.editable}>{project.name}</option
						>{/each}
				</select>
			</label>
		{/if}
		<Menu positioning={{ placement: 'bottom-end', gutter: 6 }}>
			<Menu.Trigger
				class="inline-flex min-h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-surface-300-700 bg-surface-50-950 px-2.5 py-1.5 text-sm font-semibold text-surface-700-300 transition-colors hover:bg-surface-200-800 hover:text-primary-800-200"
				aria-label={$t('Download')}
			>
				<Icon name="download" /> <span class="hidden sm:inline">{$t('Download')}</span>
				<span class="hidden sm:inline-flex"><Icon name="chevron-down" size={14} /></span>
			</Menu.Trigger>
			<Portal>
				<Menu.Positioner class="z-100">
					<Menu.Content
						class="z-1000 w-[min(22rem,calc(100vw-1rem))] rounded-container border border-surface-300-700 bg-surface-50-950 p-1.5 shadow-xl"
					>
						<div class="px-2.5 py-2 text-xs font-bold tracking-wide text-surface-600-400 uppercase">
							{$t('Current PDF')}
						</div>
						<Menu.Item
							value="download-original"
							class="flex cursor-pointer items-center rounded-md text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
						>
							<button
								type="button"
								class="w-full cursor-pointer px-2.5 py-2 text-left"
								onclick={downloadOriginal}>{$t('Download original')}</button
							>
						</Menu.Item>
						<div class="m-1 h-px bg-surface-300-700"></div>
						<label
							class="grid grid-cols-1 gap-1.5 px-2.5 py-2 text-xs font-medium text-surface-700-300"
						>
							{$t('Annotations to include')}
							<select
								class="min-h-9 rounded-md border border-surface-300-700 bg-surface-100-900 px-2 text-sm text-surface-900-100"
								bind:value={exportProjectId}
							>
								<option value="">{$t('Private annotations only')}</option>
								{#each viewer.data?.projects ?? [] as project (project.id)}
									<option value={project.id}
										>{$t('Private annotations and project: {name}', {
											name: project.name
										})}</option
									>
								{/each}
							</select>
						</label>
						<Menu.Item
							value="download-annotated"
							class="flex cursor-pointer items-center rounded-md text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
						>
							<button
								type="button"
								class="w-full cursor-pointer px-2.5 py-2 text-left"
								onclick={downloadAnnotated}>{$t('Download with annotations')}</button
							>
						</Menu.Item>
					</Menu.Content>
				</Menu.Positioner>
			</Portal>
		</Menu>
	</header>
	<div class="flex h-full min-h-0 flex-col overflow-hidden bg-surface-300-700">
		{#if downloadError}
			<aside
				class="flex shrink-0 border-b border-error-300-700 bg-error-50-950 px-3 py-1.5 text-xs font-medium text-error-800-200"
				role="alert"
			>
				{downloadError}
			</aside>
		{/if}
		{#if annotationSyncFailed && annotationStatus}
			<aside
				class="flex shrink-0 items-center justify-between gap-2 border-b border-error-300-700 bg-error-50-950 px-3 py-1.5 text-xs font-medium text-error-800-200"
				role="alert"
			>
				<span class="truncate">{annotationStatus}</span>
				<button
					type="button"
					class="cursor-pointer font-semibold text-error-800-200 hover:underline"
					onclick={() => {
						annotationSyncFailed = false;
					}}>{$t('Dismiss')}</button
				>
			</aside>
		{/if}
		{#if viewer.isPending}<div
				class="grid min-h-0 flex-1 grid-cols-1 place-items-center text-surface-600-400"
			>
				{$t('Loading reader configuration…')}
			</div>
		{:else if viewer.isError}<div
				class="grid min-h-0 flex-1 grid-cols-1 place-items-center text-error-700-300"
			>
				{$t('Unable to open this PDF.')}
			</div>
		{:else if viewer.data}
			<!-- EmbedPDF document permissions are fixed at initialization. -->
			{#key `${revisionId}:${viewer.data.editable}`}<EmbeddedPdfViewer
					{itemId}
					{workspaceId}
					documentId={revisionId}
					name={viewer.data.revision.original_name}
					url={viewer.data.revision.content_url}
					{editable}
					canModifyAnnotations={viewer.data.editable}
					annotationAuthor={viewer.data.annotation_author}
					pageGeometry={viewer.data.revision.page_geometry}
					{sources}
					{writeProject}
					onstatus={(text, failed, reason) => {
						annotationStatus = text;
						annotationSyncFailed = failed;
						if (reason instanceof ApiError && reason.code === 'project_lifecycle_error') {
							void viewer.refetch();
						}
					}}
				/>{/key}{/if}
	</div>
</div>
