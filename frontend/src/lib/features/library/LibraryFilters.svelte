<script lang="ts">
	import Icon from '$lib/design/Icon.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import type { LibraryProject, LibraryTag } from '$lib/features/library/queries';
	import { t } from '$lib/i18n';
	import Button from '$lib/design/Button.svelte';

	let {
		query = $bindable(''),
		tag = $bindable(''),
		project = $bindable(''),
		year = $bindable(''),
		keyword = $bindable(''),
		author = $bindable(''),
		filtersOpen = $bindable(false),
		tags = [],
		projects = [],
		onSearch,
		onClear
	} = $props<{
		query: string;
		tag: string;
		project: string;
		year: string;
		keyword: string;
		author: string;
		filtersOpen: boolean;
		tags: LibraryTag[];
		projects: LibraryProject[];
		onSearch: () => void;
		onClear: () => void;
	}>();
</script>

<Panel
	as="form"
	class="grid grid-cols-1 gap-3"
	onsubmit={(event) => {
		event.preventDefault();
		onSearch();
	}}
>
	<div class="flex flex-wrap items-center gap-2">
		<span class="ml-1 text-surface-600-400"><Icon name="search" /></span>
		<input
			class="min-w-40 flex-1 border-0 bg-transparent px-1 py-2 text-base outline-none placeholder:text-surface-600-400"
			bind:value={query}
			placeholder={$t('Search title, author, Tag, or full text')}
		/>
		<Button
			type="button"
			class="ml-auto"
			aria-expanded={filtersOpen}
			onclick={() => (filtersOpen = !filtersOpen)}>{$t('Filters')}</Button
		>
		<Button variant="filled">{$t('Search')}</Button>
	</div>
	{#if filtersOpen}
		<div
			class="grid grid-cols-1 gap-3 border-t border-surface-300-700 pt-4 sm:grid-cols-2 xl:grid-cols-5"
		>
			<label
				>{$t('Tag')}<select class="select" bind:value={tag}
					><option value="">{$t('All Tags')}</option>{#each tags as option (option.id)}<option
							value={option.id}>{option.name}</option
						>{/each}</select
				></label
			>
			<label
				>{$t('Project')}<select class="select" bind:value={project}
					><option value="">{$t('All Projects')}</option
					>{#each projects as option (option.id)}<option value={option.id}>{option.name}</option
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
		<div class="flex flex-wrap justify-end gap-2">
			<Button type="button" onclick={onClear}>{$t('Clear filters')}</Button>
		</div>
	{/if}
</Panel>
