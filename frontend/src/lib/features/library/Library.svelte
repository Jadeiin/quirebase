<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { SvelteSet, SvelteURLSearchParams } from 'svelte/reactivity';
	import { isDownloadCancelled } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import ConfirmDialog from '$lib/design/ConfirmDialog.svelte';
	import StatusNotice from '$lib/design/StatusNotice.svelte';
	import BulkActions from '$lib/features/library/BulkActions.svelte';
	import LibraryFilters from '$lib/features/library/LibraryFilters.svelte';
	import LibraryResults from '$lib/features/library/LibraryResults.svelte';
	import {
		libraryBulkMutationOptions,
		type LibraryBulkAction
	} from '$lib/features/library/mutations';
	import { libraryListQuery } from '$lib/features/library/queries';
	import { projectListQuery } from '$lib/features/projects/queries';
	import { tagsQuery } from '$lib/features/tags/queries';
	import { getSession } from '$lib/session';
	import {
		defaultExportPreferences,
		readExportPreferences,
		type ExportPreferences
	} from '$lib/export-preferences';
	import { t } from '$lib/i18n';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';
	import { canRunBulkAction } from '$lib/workspaces/actions';
	import { workspaceHref } from '$lib/workspaces/href';

	const submitted = $derived({
		query: page.url.searchParams.get('q')?.trim() ?? '',
		tag: page.url.searchParams.get('tag') ?? '',
		project: page.url.searchParams.get('project') ?? '',
		year: page.url.searchParams.get('year')?.trim() ?? '',
		keyword: page.url.searchParams.get('keyword')?.trim() ?? '',
		author: page.url.searchParams.get('author')?.trim() ?? ''
	});
	const pageNumber = $derived(Math.max(1, Number(page.url.searchParams.get('page') ?? '1') || 1));
	let query = $state(page.url.searchParams.get('q') ?? '');
	let tag = $state(page.url.searchParams.get('tag') ?? '');
	let project = $state(page.url.searchParams.get('project') ?? '');
	let year = $state(page.url.searchParams.get('year') ?? '');
	let keyword = $state(page.url.searchParams.get('keyword') ?? '');
	let author = $state(page.url.searchParams.get('author') ?? '');
	let filtersOpen = $state(false);
	let selected = new SvelteSet<string>();
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
		selected.clear();
	});

	const library = createQuery(() => libraryListQuery(workspaceId, submitted, pageNumber));
	const tags = createQuery(() => tagsQuery(workspaceId));
	const projects = createQuery(() => projectListQuery(workspaceId));
	const totalPages = $derived(
		Math.max(1, Math.ceil((library.data?.total ?? 0) / (library.data?.per_page ?? 25)))
	);
	const allPageSelected = $derived(
		((library.data?.items.length ?? 0) > 0 &&
			library.data?.items.every((item) => selected.has(item.id))) ??
			false
	);

	$effect(() => {
		if (session.data?.user) {
			const loadedPreferences = readExportPreferences(session.data.user.id);
			exportPreferences = loadedPreferences;
			exportFormat = loadedPreferences.citation.format;
		}
	});

	function parameters(nextPage = 1) {
		const result = new SvelteURLSearchParams();
		for (const [key, value] of Object.entries({
			q: query.trim(),
			tag,
			project,
			year: year.trim(),
			keyword: keyword.trim(),
			author: author.trim()
		})) {
			if (value) result.set(key, value);
		}
		if (nextPage > 1) result.set('page', String(nextPage));
		return result;
	}

	function updateUrl(nextPage = 1) {
		const values = parameters(nextPage).toString();
		selected.clear();
		void goto(resolve(workspaceHref(workspaceId, values ? `library?${values}` : 'library')), {
			keepFocus: true,
			noScroll: true
		});
	}

	function clearFilters() {
		query = '';
		tag = '';
		project = '';
		year = '';
		keyword = '';
		author = '';
		updateUrl();
	}

	function togglePageSelection(event: Event) {
		const checked = (event.currentTarget as HTMLInputElement).checked;
		for (const item of library.data?.items ?? []) {
			if (checked) selected.add(item.id);
			else selected.delete(item.id);
		}
	}

	function toggleItem(id: string) {
		if (selected.has(id)) selected.delete(id);
		else selected.add(id);
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
				afterMutation: () => selected.clear()
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
	bind:filtersOpen
	tags={tags.data ?? []}
	projects={projects.data ?? []}
	onSearch={() => updateUrl()}
	onClear={clearFilters}
/>

<BulkActions
	selectedCount={selected.size}
	bind:bulkAction
	bind:bulkProject
	bind:bulkTag
	bind:exportFormat
	projects={projects.data ?? []}
	{busy}
	onApply={requestBulkAction}
	onClearSelection={() => selected.clear()}
/>

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
	{totalPages}
	{allPageSelected}
	{selected}
	onTogglePage={togglePageSelection}
	onToggleItem={toggleItem}
	onPage={(next) => updateUrl(next)}
/>
