<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import Button from '#lib/design/Button.svelte';
	import { tagsQuery } from '#lib/features/tags/queries.js';
	import { metadataValueLabel } from '#lib/features/item/metadata-labels.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { t } from '#lib/i18n.js';
	import type { LibraryFilters } from './filters.js';

	let {
		filters,
		onRemove
	}: {
		filters: LibraryFilters;
		onRemove: (keys: (keyof LibraryFilters)[]) => void;
	} = $props();
	const { workspaceId } = getWorkspaceContext();
	const tag = createQuery(() => ({
		...tagsQuery(workspaceId, '', 0, 1, filters.tag),
		enabled: Boolean(filters.tag)
	}));
	const chips = $derived.by(() => {
		const result: { label: string; value: string; keys: (keyof LibraryFilters)[] }[] = [];
		if (filters.author_last_name !== undefined)
			result.push({
				label: $t('Author'),
				value: [filters.author_last_name, filters.author_first_name].filter(Boolean).join(', '),
				keys: ['author_last_name', 'author_first_name']
			});
		if (filters.author)
			result.push({ label: $t('Contributor'), value: filters.author, keys: ['author'] });
		if (filters.year) result.push({ label: $t('Year'), value: filters.year, keys: ['year'] });
		if (filters.publication_title !== undefined)
			result.push({
				label: $t('Publication'),
				value: filters.publication_title,
				keys: ['publication_title']
			});
		if (filters.reference_type !== undefined)
			result.push({
				label: $t('Type'),
				value: metadataValueLabel(filters.reference_type),
				keys: ['reference_type']
			});
		if (filters.tag)
			result.push({
				label: $t('Tag'),
				value: tag.data?.items[0]?.name ?? filters.tag,
				keys: ['tag']
			});
		if (filters.keyword_exact !== undefined)
			result.push({ label: $t('Keyword'), value: filters.keyword_exact, keys: ['keyword_exact'] });
		if (filters.keyword)
			result.push({ label: $t('Keyword'), value: filters.keyword, keys: ['keyword'] });
		return result;
	});
</script>

{#if chips.length}
	<div
		class="mt-3 flex flex-wrap items-center gap-2"
		role="group"
		aria-label={$t('Applied filters')}
	>
		{#each chips as chip (chip.keys[0])}
			<Button
				size="sm"
				onclick={() => onRemove(chip.keys)}
				aria-label={$t('Remove filter {name}', { name: `${chip.label}: ${chip.value}` })}
			>
				{chip.label}: {chip.value}<span aria-hidden="true"> ×</span>
			</Button>
		{/each}
	</div>
{/if}
