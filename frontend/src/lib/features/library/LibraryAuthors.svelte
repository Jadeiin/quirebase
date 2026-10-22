<script lang="ts">
	import { resolve } from '$app/paths';
	import AuthorLine from '#lib/design/AuthorLine.svelte';
	import { t } from '#lib/i18n.js';
	import type { libraryHref, LibraryMetadataFilter } from './filters.js';
	import type { LibrarySearch } from './queries.js';

	let {
		authors,
		filterHref,
		previewOpen,
		onShowAll
	}: {
		authors: LibrarySearch['items'][number]['authors'];
		filterHref: (filter: LibraryMetadataFilter) => ReturnType<typeof libraryHref>;
		previewOpen: boolean;
		onShowAll: (trigger: HTMLElement) => void;
	} = $props();
</script>

{#if authors.length}
	<AuthorLine
		names={authors.map((author) => author.full_name)}
		{onShowAll}
		expanded={previewOpen}
		controls="library-preview"
	>
		{#snippet author(index: number)}
			{@const credit = authors[index]}
			<a
				dir="auto"
				class="text-surface-700-300 no-underline underline-offset-4 hover:text-primary-700-300 hover:underline focus-visible:underline"
				href={resolve(
					filterHref({
						author_last_name: credit.last_name,
						author_first_name: credit.first_name ?? ''
					})
				)}
				title={$t('View Items by {name}', { name: credit.full_name })}
				aria-label={$t('View Items by {name}', { name: credit.full_name })}>{credit.full_name}</a
			>
		{/snippet}
	</AuthorLine>
{:else}
	<span class="block truncate">{$t('Unknown authors')}</span>
{/if}
