<script lang="ts">
	import DateField from '#lib/design/DateField.svelte';
	import { Collapsible } from '@skeletonlabs/skeleton-svelte';
	import ProjectSelect from '#lib/features/projects/ProjectSelect.svelte';
	import TagSelect from '#lib/features/tags/TagSelect.svelte';
	import { buttonClass } from '#lib/design/button-classes.js';
	import Icon from '#lib/design/Icon.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import { t } from '#lib/i18n.js';
	import Button from '#lib/design/Button.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import type { LibraryFilters, LibraryMetadataFilter, libraryHref } from './filters.js';

	let {
		searchInput = $bindable(),
		shortcutsEnabled,
		query = $bindable(''),
		tag = $bindable(''),
		project = $bindable(''),
		year = $bindable(''),
		keyword = $bindable(''),
		author = $bindable(''),
		fileFilter = $bindable(''),
		filtersOpen = $bindable(false),
		applied,
		filterHref,
		onSearch,
		onClear
	}: {
		searchInput: HTMLInputElement | undefined;
		shortcutsEnabled: boolean;
		query: string;
		tag: string;
		project: string;
		year: string;
		keyword: string;
		author: string;
		fileFilter: string;
		filtersOpen: boolean;
		applied: LibraryFilters;
		filterHref: (filter: LibraryMetadataFilter) => ReturnType<typeof libraryHref>;
		onSearch: () => void;
		onClear: () => void;
	} = $props();
	let refinementAttempt = $state(0);
</script>

<Panel
	as="form"
	class="grid grid-cols-1 gap-3"
	onsubmit={(event) => {
		event.preventDefault();
		onSearch();
	}}
>
	<Collapsible
		open={filtersOpen}
		onOpenChange={(details) => (filtersOpen = details.open)}
		class="items-stretch"
	>
		<div class="flex flex-wrap items-center gap-2">
			<span class="ml-1 text-surface-600-400"><Icon name="search" /></span>
			<input
				bind:this={searchInput}
				aria-label={$t('Library Search')}
				aria-keyshortcuts={shortcutsEnabled ? '/' : undefined}
				class="min-w-40 flex-1 border-0 bg-transparent px-1 py-2 text-base outline-none placeholder:text-surface-600-400"
				bind:value={query}
				placeholder={$t('Search title, author, Tag, or full text')}
			/>
			{#if shortcutsEnabled}<kbd class="hidden kbd text-xs pointer-fine:inline" aria-hidden="true"
					>/</kbd
				>{/if}
			<Collapsible.Trigger class={`ml-auto ${buttonClass('tonal')}`}
				>{$t('Filters')}</Collapsible.Trigger
			>
			<Button variant="filled">{$t('Search')}</Button>
		</div>
		<Collapsible.Content class="grid grid-cols-1 gap-3">
			<div
				class="grid grid-cols-1 gap-3 border-t border-surface-300-700 pt-4 sm:grid-cols-2 xl:grid-cols-5"
			>
				<TagSelect label={$t('Tag')} bind:value={tag} emptyLabel={$t('All Tags')} />
				<ProjectSelect label={$t('Project')} bind:value={project} emptyLabel={$t('All Projects')} />
				<DateField precision="year" label={$t('Year')} bind:value={year} />
				<label>{$t('Contributor')}<input class="input" bind:value={author} /></label>
				<label>{$t('Keyword')}<input class="input" bind:value={keyword} /></label>
				<label
					>{$t('Files')}<select class="select" bind:value={fileFilter}>
						<option value="">{$t('All Items')}</option><option value="true"
							>{$t('With files')}</option
						>
						<option value="false">{$t('Without files')}</option>
					</select></label
				>
			</div>
			<div class="flex flex-wrap justify-end gap-2">
				<Button type="button" onclick={onClear}>{$t('Clear filters')}</Button>
			</div>
			{#if filtersOpen}
				{#key refinementAttempt}
					{#await import('./LibraryRefinements.svelte')}
						<p role="status" class="text-sm text-surface-600-400">{$t('Loading filter values…')}</p>
					{:then { default: LibraryRefinements }}
						<LibraryRefinements filters={applied} {filterHref} />
					{:catch}
						<QueryError
							message={$t('Unable to load filter values.')}
							onRetry={() => refinementAttempt++}
						/>
					{/await}
				{/key}
			{/if}
		</Collapsible.Content>
	</Collapsible>
</Panel>
