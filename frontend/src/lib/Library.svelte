<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { SvelteSet, SvelteURLSearchParams } from 'svelte/reactivity';
	import {
		apiDownload,
		apiRequest,
		type LibraryView,
		type ProjectSummary,
		type SessionView
	} from '$lib/api/client';
	import Icon from '$lib/design/Icon.svelte';
	import RichText from '$lib/design/RichText.svelte';
	import {
		defaultExportPreferences,
		readExportPreferences,
		type ExportPreferences
	} from '$lib/export-preferences';
	import { t } from '$lib/i18n';

	type Tag = { id: string; name: string; accessible_item_count: number };
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
	let busy = $state(false);
	let error = $state('');
	let notice = $state('');
	let exportPreferences = $state<ExportPreferences>(structuredClone(defaultExportPreferences));
	const queryClient = useQueryClient();
	const session = createQuery(() => ({
		queryKey: ['session'],
		queryFn: () => apiRequest<SessionView>('/session')
	}));

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

	const library = createQuery(() => ({
		queryKey: ['library', submitted, pageNumber],
		queryFn: () => {
			const parameters = new SvelteURLSearchParams();
			parameters.set('page', String(pageNumber));
			if (submitted.query) parameters.set('query', submitted.query);
			for (const [key, value] of Object.entries({
				tag: submitted.tag,
				project: submitted.project,
				year: submitted.year,
				keyword: submitted.keyword,
				author: submitted.author
			})) {
				if (value) parameters.set(key, value);
			}
			return apiRequest<LibraryView>(`/items?${parameters}`);
		}
	}));
	const tags = createQuery(() => ({
		queryKey: ['tags'],
		queryFn: () => apiRequest<Tag[]>('/tags')
	}));
	const projects = createQuery(() => ({
		queryKey: ['projects'],
		queryFn: () => apiRequest<ProjectSummary[]>('/projects')
	}));
	const totalPages = $derived(
		Math.max(1, Math.ceil((library.data?.total ?? 0) / (library.data?.per_page ?? 25)))
	);
	const allPageSelected = $derived(
		(library.data?.items.length ?? 0) > 0 &&
			library.data?.items.every((item) => selected.has(item.id))
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
		void goto(resolve(values ? `/library?${values}` : '/library'), {
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

	async function runBulkAction() {
		if (!bulkAction || selected.size === 0) return;
		if (bulkAction === 'delete' && !window.confirm($t('Permanently delete the selected Items?')))
			return;
		busy = true;
		error = '';
		notice = '';
		try {
			if (bulkAction === 'bibliography') {
				const citation = exportPreferences.citation;
				await apiDownload('/items/bibliography', {
					item_ids: [...selected],
					file_format: exportFormat,
					style: citation.style,
					include_abstract: citation.includeAbstract,
					preserve_case: citation.preserveCase,
					include_identifiers: citation.includeIdentifiers,
					include_custom_fields: citation.includeCustomFields,
					encoding: citation.encoding,
					journal_mode: citation.journalMode,
					doi_policy: citation.doiPolicy,
					url_policy: citation.urlPolicy,
					excluded_fields: citation.excludedFields
						.split(',')
						.map((value) => value.trim())
						.filter(Boolean),
					sort_by: citation.sortBy,
					citation_key_formula: citation.citationKeyFormula,
					citation_key_force_ascii: citation.citationKeyForceAscii
				});
			} else if (bulkAction === 'documents') {
				await apiDownload('/items/documents/archive', {
					item_ids: [...selected],
					include_annotations: exportPreferences.document.includeAnnotations,
					include_supplements: exportPreferences.document.includeSupplements,
					timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
				});
			} else {
				await apiRequest('/items/bulk', {
					method: 'POST',
					body: {
						item_ids: [...selected],
						action: bulkAction,
						project_id: bulkProject,
						tag_name: bulkTag,
						confirmation: bulkAction === 'delete' ? 'delete' : ''
					}
				});
				selected.clear();
				const invalidations = [
					queryClient.invalidateQueries({ queryKey: ['library'] }),
					queryClient.invalidateQueries({ queryKey: ['dashboard'] })
				];
				if (bulkAction === 'add_project' && bulkProject) {
					invalidations.push(
						queryClient.invalidateQueries({ queryKey: ['project', bulkProject] }),
						queryClient.invalidateQueries({ queryKey: ['projects'] })
					);
				}
				await Promise.all(invalidations);
			}
			notice = $t('Bulk action completed');
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Bulk action failed');
		} finally {
			busy = false;
		}
	}
</script>

<div class="mb-8 flex items-end justify-between gap-4">
	<div>
		<p class="mb-2 text-xs font-bold tracking-[0.12em] text-primary-700 uppercase">
			{$t('Workspace')}
		</p>
		<h1 class="mb-2">{$t('Library')}</h1>
		<p class="m-0 max-w-2xl text-surface-700">
			{$t('Search, select, organize, and export your scholarly Items.')}
		</p>
	</div>
	{#if library.data}<span
			class="hidden rounded-full border border-surface-300 bg-surface-50 px-3 py-1.5 text-xs font-semibold text-surface-600 sm:inline"
			>{library.data.total} {$t('Items')}</span
		>{/if}
</div>

<form
	class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm"
	onsubmit={(event) => {
		event.preventDefault();
		updateUrl();
	}}
>
	<div class="flex items-center gap-2">
		<span class="ml-1 text-surface-600"><Icon name="search" /></span>
		<input
			class="min-w-0 flex-1 border-0 bg-transparent px-1 py-2 text-base outline-none placeholder:text-surface-600"
			bind:value={query}
			placeholder={$t('Search title, author, Tag, or full text')}
		/>
		<button
			type="button"
			class="btn preset-tonal-surface font-semibold"
			aria-expanded={filtersOpen}
			onclick={() => (filtersOpen = !filtersOpen)}>{$t('Filters')}</button
		>
		<button class="btn preset-filled-primary-700-300 font-semibold">{$t('Search')}</button>
	</div>
	{#if filtersOpen}
		<div class="grid gap-3 border-t border-surface-300 pt-4 sm:grid-cols-2 xl:grid-cols-5">
			<label
				>{$t('Tag')}<select class="select" bind:value={tag}
					><option value="">{$t('All Tags')}</option
					>{#each tags.data ?? [] as option (option.id)}<option value={option.id}
							>{option.name}</option
						>{/each}</select
				></label
			>
			<label
				>{$t('Project')}<select class="select" bind:value={project}
					><option value="">{$t('All Projects')}</option
					>{#each projects.data ?? [] as option (option.id)}<option value={option.id}
							>{option.name}</option
						>{/each}</select
				></label
			>
			<label
				>{$t('Year')}<input
					class="input"
					inputmode="numeric"
					maxlength="4"
					bind:value={year}
				/></label
			>
			<label>{$t('Contributor')}<input class="input" bind:value={author} /></label>
			<label>{$t('Keyword')}<input class="input" bind:value={keyword} /></label>
		</div>
		<div class="toolbar justify-end">
			<button type="button" class="btn preset-tonal-surface font-semibold" onclick={clearFilters}
				>{$t('Clear filters')}</button
			>
		</div>
	{/if}
</form>

{#if selected.size}
	<section
		class="sticky top-3 z-30 mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-primary-700/30 bg-surface-50 p-3 shadow-lg"
	>
		<strong class="mr-2">{selected.size} {$t('selected')}</strong>
		<select class="compact input" bind:value={bulkAction} aria-label={$t('Bulk action')}>
			<option value="">{$t('Choose action')}</option>
			<option value="add_project">{$t('Add to Project')}</option>
			<option value="add_tag">{$t('Add Tag')}</option>
			<option value="bibliography">{$t('Export bibliography')}</option>
			<option value="documents">{$t('Download documents')}</option>
			<option value="delete">{$t('Permanently delete')}</option>
		</select>
		{#if bulkAction === 'add_project'}<select
				class="compact input"
				bind:value={bulkProject}
				aria-label={$t('Select Project')}
				><option value="">{$t('Select Project')}</option
				>{#each projects.data ?? [] as option (option.id)}<option value={option.id}
						>{option.name}</option
					>{/each}</select
			>{/if}
		{#if bulkAction === 'add_tag'}<input
				class="compact input"
				bind:value={bulkTag}
				placeholder={$t('Tag name')}
			/>{/if}
		{#if bulkAction === 'bibliography'}<select class="compact input" bind:value={exportFormat}
				><option value="bibtex">BibTeX</option><option value="biblatex">BibLaTeX</option><option
					value="ris">RIS</option
				><option value="endnote">EndNote</option><option value="csl">CSL</option></select
			>{/if}
		<button
			class="btn preset-filled-primary-700-300 font-semibold"
			disabled={busy ||
				!bulkAction ||
				(bulkAction === 'add_project' && !bulkProject) ||
				(bulkAction === 'add_tag' && !bulkTag.trim())}
			onclick={runBulkAction}>{$t('Apply')}</button
		>
		<button class="btn preset-tonal-surface font-semibold" onclick={() => selected.clear()}
			>{$t('Clear selection')}</button
		>
	</section>
{/if}

{#if error}<p class="mt-4 text-error-700" role="alert">{error}</p>{/if}
{#if notice}<p
		class="mt-4 rounded-base border border-success-200 preset-tonal-success px-4 py-3 text-success-900"
		role="status"
	>
		{notice}
	</p>{/if}

<section class="mt-6 overflow-hidden rounded-xl border border-surface-300 bg-surface-50 shadow-sm">
	{#if library.isPending}<div class="grid min-h-56 place-items-center text-surface-600">
			{$t('Loading Library…')}
		</div>
	{:else if library.isError}<div class="grid min-h-56 place-items-center text-error-700">
			{$t('Unable to load the Library.')}
		</div>
	{:else if !library.data?.items.length}<div
			class="grid min-h-56 place-items-center gap-2 p-8 text-center"
		>
			<span class="grid size-12 place-items-center rounded-full bg-surface-200 text-surface-600"
				><Icon name="library" size={22} /></span
			><strong>{$t('No Items found.')}</strong><span class="text-sm text-surface-600"
				>{$t('Try a different Library Search.')}</span
			>
		</div>
	{:else}
		<div
			class="bg-surface/60 flex items-center gap-3 border-b border-surface-300 px-5 py-3 text-sm"
		>
			<input
				type="checkbox"
				checked={allPageSelected}
				onchange={togglePageSelection}
				aria-label={$t('Select this page')}
			/><span class="font-semibold">{$t('Select this page')}</span>
		</div>
		<div class="divide-line divide-y">
			{#each library.data.items as item (item.id)}
				<article
					class="group grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-5 py-4 transition-colors hover:bg-primary-50/60"
				>
					<input
						type="checkbox"
						checked={selected.has(item.id)}
						onchange={() =>
							selected.has(item.id) ? selected.delete(item.id) : selected.add(item.id)}
						aria-label={`${$t('Select')} ${item.authors ?? ''}`}
					/>
					<a
						class="grid min-w-0 gap-1 no-underline"
						href={resolve('/(app)/item/[itemId]', { itemId: item.id })}
						><strong class="text-[0.98rem] leading-snug group-hover:text-primary-800"
							><RichText html={item.title_html} /></strong
						><span class="truncate text-sm text-surface-600"
							>{item.authors || $t('Unknown authors')}</span
						>{#if item.publication_title}<span class="truncate text-xs text-surface-600"
								>{item.publication_title}</span
							>{/if}</a
					>
					<span class="flex items-center gap-2 text-xs text-surface-600"
						>{item.publication_date || '—'}<Icon name="chevron-right" size={16} /></span
					>
				</article>
			{/each}
		</div>
		<nav
			class="bg-surface/60 flex items-center justify-center gap-1 border-t border-surface-300 px-4 py-3"
			aria-label={$t('Library pages')}
		>
			<button
				type="button"
				class="inline-grid size-9 place-items-center rounded-md border border-surface-300 bg-surface-50 text-surface-600 hover:bg-primary-50 hover:text-primary-800 disabled:opacity-35"
				disabled={pageNumber <= 1}
				aria-label={$t('First page')}
				title={$t('First page')}
				onclick={() => updateUrl(1)}><Icon name="chevrons-left" size={17} /></button
			>
			<button
				type="button"
				class="inline-grid size-9 place-items-center rounded-md border border-surface-300 bg-surface-50 text-surface-600 hover:bg-primary-50 hover:text-primary-800 disabled:opacity-35"
				disabled={pageNumber <= 1}
				aria-label={$t('Previous page')}
				title={$t('Previous page')}
				onclick={() => updateUrl(pageNumber - 1)}><Icon name="chevron-left" size={17} /></button
			>
			<span class="min-w-24 px-2 text-center text-xs font-medium text-surface-600 tabular-nums"
				>{$t('Page')} {pageNumber} {$t('of')} {totalPages}</span
			>
			<button
				type="button"
				class="inline-grid size-9 place-items-center rounded-md border border-surface-300 bg-surface-50 text-surface-600 hover:bg-primary-50 hover:text-primary-800 disabled:opacity-35"
				disabled={pageNumber >= totalPages}
				aria-label={$t('Next page')}
				title={$t('Next page')}
				onclick={() => updateUrl(pageNumber + 1)}><Icon name="chevron-right" size={17} /></button
			>
			<button
				type="button"
				class="inline-grid size-9 place-items-center rounded-md border border-surface-300 bg-surface-50 text-surface-600 hover:bg-primary-50 hover:text-primary-800 disabled:opacity-35"
				disabled={pageNumber >= totalPages}
				aria-label={$t('Last page')}
				title={$t('Last page')}
				onclick={() => updateUrl(totalPages)}><Icon name="chevrons-right" size={17} /></button
			>
		</nav>
	{/if}
</section>
