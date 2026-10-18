<script lang="ts">
	import Button from '#lib/design/Button.svelte';
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		createMutation,
		createInfiniteQuery,
		createQuery,
		useQueryClient
	} from '@tanstack/svelte-query';
	import { SvelteSet } from 'svelte/reactivity';
	import { isDownloadCancelled } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import ConfirmDialog from '#lib/design/ConfirmDialog.svelte';
	import StatusNotice from '#lib/design/StatusNotice.svelte';
	import BulkActions from '#lib/features/library/BulkActions.svelte';
	import LibraryFilters from '#lib/features/library/LibraryFilters.svelte';
	import LibraryResults from '#lib/features/library/LibraryResults.svelte';
	import {
		libraryBulkMutationOptions,
		type LibraryBulkAction
	} from '#lib/features/library/mutations.js';
	import { libraryListQuery } from '#lib/features/library/queries.js';
	import {
		librarySort,
		readLibraryFilters,
		libraryPage,
		libraryPageSize,
		libraryHref,
		type LibraryFilters as AppliedLibraryFilters
	} from './filters.js';
	import LibraryActiveFilters from './LibraryActiveFilters.svelte';
	import { projectDetailQuery, projectOptionsQuery } from '#lib/features/projects/queries.js';
	import { getSession } from '#lib/session.js';
	import {
		defaultExportPreferences,
		readExportPreferences,
		type ExportPreferences
	} from '#lib/export-preferences.js';
	import { t } from '#lib/i18n.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { canRunBulkAction } from '#lib/workspaces/actions.js';

	const submitted = $derived(readLibraryFilters(page.url.searchParams));
	const pageNumber = $derived(libraryPage(page.url.searchParams));
	const pageSize = $derived(libraryPageSize(page.url.searchParams));
	let query = $state(page.url.searchParams.get('q') ?? '');
	let tag = $state(page.url.searchParams.get('tag') ?? '');
	let project = $state(page.url.searchParams.get('project') ?? '');
	let year = $state(page.url.searchParams.get('year') ?? '');
	let keyword = $state(page.url.searchParams.get('keyword') ?? '');
	let author = $state(page.url.searchParams.get('author') ?? '');
	let fileFilter = $state(page.url.searchParams.get('has_files') ?? '');
	let filtersOpen = $state(false);
	let selected = new SvelteSet<string>();
	let selectionVersion = 0;
	let bulkAction = $state('');
	let bulkProject = $state('');
	let bulkTag = $state('');
	let exportFormat = $state('bibtex');
	let error = $state('');
	let notice = $state('');
	let confirmDeleteOpen = $state(false);
	let exportPreferences = $state<ExportPreferences>(structuredClone(defaultExportPreferences));
	const queryClient = useQueryClient();
	const workspace = getWorkspaceContext();
	const { workspaceId } = workspace;
	const { query: session } = getSession();
	const bulkMutation = createMutation(() => libraryBulkMutationOptions(workspaceId, queryClient));
	const busy = $derived(bulkMutation.isPending);

	let previousSearch = page.url.search;
	$effect(() => {
		const search = page.url.search;
		if (search === previousSearch) return;
		previousSearch = search;
		query = page.url.searchParams.get('q') ?? '';
		tag = page.url.searchParams.get('tag') ?? '';
		project = page.url.searchParams.get('project') ?? '';
		year = page.url.searchParams.get('year') ?? '';
		keyword = page.url.searchParams.get('keyword') ?? '';
		author = page.url.searchParams.get('author') ?? '';
		fileFilter = page.url.searchParams.get('has_files') ?? '';
		clearSelection();
	});

	const library = createQuery(() => libraryListQuery(workspaceId, submitted, pageNumber, pageSize));
	const projects = createInfiniteQuery(() => projectOptionsQuery(workspaceId));
	const selectedProject = createQuery(() => ({
		...projectDetailQuery(workspaceId, submitted.project ?? ''),
		enabled: Boolean(submitted.project) && !projects.data?.some((p) => p.id === submitted.project)
	}));
	const projectChoices = $derived(
		selectedProject.data && !projects.data?.some((p) => p.id === selectedProject.data?.id)
			? [selectedProject.data, ...(projects.data ?? [])]
			: (projects.data ?? [])
	);
	const totalPages = $derived(Math.max(1, Math.ceil((library.data?.total ?? 0) / pageSize)));
	$effect(() => {
		if (library.isSuccess && !library.isFetching && pageNumber > totalPages) {
			void goto(resolve(libraryHref(workspaceId, submitted, totalPages, pageSize)), {
				reset: false,
				replaceState: true
			});
		}
	});
	const allPageSelected = $derived(
		((library.data?.items.length ?? 0) > 0 &&
			library.data?.items.every((item) => selected.has(item.id))) ??
			false
	);

	$effect(() => {
		if (session.data?.user) {
			const loadedPreferences = readExportPreferences(session.data.user.id, workspaceId);
			exportPreferences = loadedPreferences;
			exportFormat = loadedPreferences.citation.format;
		}
	});

	function navigate(filters: AppliedLibraryFilters, nextPage = 1, nextPageSize = pageSize) {
		clearSelection();
		void goto(resolve(libraryHref(workspaceId, filters, nextPage, nextPageSize)), { reset: false });
	}

	function search() {
		navigate({
			...submitted,
			query: query.trim(),
			tag,
			project,
			year: year.trim(),
			keyword: keyword.trim(),
			author: author.trim(),
			has_files: fileFilter ? fileFilter === 'true' : undefined
		});
	}

	function removeFilters(keys: (keyof AppliedLibraryFilters)[]) {
		const next = { ...submitted };
		for (const key of keys) delete next[key];
		navigate(next);
	}

	function clearFilters() {
		query = tag = project = year = keyword = author = fileFilter = '';
		navigate({ sort: submitted.sort });
	}

	function togglePageSelection(event: Event) {
		selectionVersion++;
		const checked = (event.currentTarget as HTMLInputElement).checked;
		for (const item of library.data?.items ?? []) {
			if (checked) selected.add(item.id);
			else selected.delete(item.id);
		}
	}

	function toggleItem(id: string) {
		selectionVersion++;
		if (selected.has(id)) selected.delete(id);
		else selected.add(id);
	}

	function clearSelection() {
		selectionVersion++;
		selected.clear();
	}

	function requestBulkAction() {
		if (!bulkAction || selected.size === 0 || bulkMutation.isPending) return;
		if (!canRunBulkAction(workspace.can, bulkAction as LibraryBulkAction)) return;
		if (bulkAction === 'delete') {
			confirmDeleteOpen = true;
			return;
		}
		void executeBulkAction();
	}

	async function executeBulkAction() {
		confirmDeleteOpen = false;
		if (!canRunBulkAction(workspace.can, bulkAction as LibraryBulkAction)) return;
		error = '';
		notice = '';
		const submittedSelectionVersion = selectionVersion;
		try {
			await bulkMutation.mutateAsync({
				input: {
					action: bulkAction as LibraryBulkAction,
					itemIds: [...selected],
					projectId: bulkProject,
					tagName: bulkTag,
					exportFormat,
					preferences: exportPreferences
				},
				afterMutation: () => {
					if (selectionVersion === submittedSelectionVersion) clearSelection();
				}
			});
			notice = $t('Bulk action completed');
		} catch (reason) {
			if (isDownloadCancelled(reason)) return;
			error = apiErrorMessage(reason, $t('Bulk action failed'));
		}
	}
</script>

<div class="mb-8 flex items-end justify-between gap-4">
	<div>
		<p class="mb-2 text-xs font-bold tracking-[0.12em] text-primary-700-300 uppercase">
			{$t('Workspace')}
		</p>
		<h1 class="mb-2">{$t('Library')}</h1>
		<p class="m-0 max-w-2xl text-surface-700-300">
			{$t('Search, select, organize, and export your scholarly Items.')}
		</p>
	</div>
	{#if library.data}<span
			class="hidden rounded-full border border-surface-300-700 bg-surface-50-950 px-3 py-1.5 text-xs font-semibold text-surface-600-400 sm:inline"
			>{$t('{count, plural, one {# Item} other {# Items}}', {
				count: library.data.total
			})}</span
		>{/if}
</div>

<LibraryFilters
	bind:query
	bind:tag
	bind:project
	bind:year
	bind:keyword
	bind:author
	bind:fileFilter
	bind:filtersOpen
	projects={projectChoices}
	onSearch={search}
	onClear={clearFilters}
/>

<LibraryActiveFilters filters={submitted} onRemove={removeFilters} />

<BulkActions
	selectedCount={selected.size}
	bind:bulkAction
	bind:bulkProject
	bind:bulkTag
	bind:exportFormat
	projects={projectChoices}
	{busy}
	onApply={requestBulkAction}
	onClearSelection={clearSelection}
/>

{#if projects.hasNextPage}<Button
		disabled={projects.isFetchingNextPage}
		onclick={() => void projects.fetchNextPage()}>{$t('Load more Projects')}</Button
	>{/if}

<ConfirmDialog
	bind:open={confirmDeleteOpen}
	title={$t('Permanently delete the selected Items?')}
	body={$t('This cannot be undone.')}
	confirmLabel={$t('Permanently delete')}
	{busy}
	onConfirm={() => void executeBulkAction()}
/>

<StatusNotice {error} {notice} />

<LibraryResults
	{workspaceId}
	data={library.data}
	isPending={library.isPending ?? false}
	isError={library.isError ?? false}
	{pageNumber}
	{pageSize}
	sort={submitted.sort ?? 'updated'}
	busy={library.isFetching}
	{totalPages}
	{allPageSelected}
	{selected}
	onTogglePage={togglePageSelection}
	onToggleItem={toggleItem}
	onPage={(next) => navigate(submitted, next)}
	onPageSize={(size) => navigate(submitted, 1, size)}
	onSort={(value) => navigate({ ...submitted, sort: librarySort(value) })}
/>
