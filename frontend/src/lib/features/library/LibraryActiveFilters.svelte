<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import Button from '#lib/design/Button.svelte';
	import { tagsQuery } from '#lib/features/tags/queries.js';
	import { metadataValueLabel } from '#lib/features/item/metadata-labels.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref, type WorkspacePath } from '#lib/workspaces/href.js';
	import { t } from '#lib/i18n.js';
	import type { LibraryFilters } from './filters.js';

	let {
		filters,
		project = null,
		onRemove
	}: {
		filters: LibraryFilters;
		project?: { id: string; name: string } | null;
		onRemove: (keys: (keyof LibraryFilters)[]) => void;
	} = $props();
	const { workspaceId } = getWorkspaceContext();
	const tag = createQuery(() => ({
		...tagsQuery(workspaceId, '', 0, 1, filters.tag),
		enabled: Boolean(filters.tag)
	}));
	const chips = $derived.by(() => {
		const result: {
			label: string;
			keys: (keyof LibraryFilters)[];
			href?: WorkspacePath;
		}[] = [];
		function add(
			label: string,
			value: string | undefined,
			keys: (keyof LibraryFilters)[],
			href?: WorkspacePath
		) {
			result.push({ label: value ? `${label}: ${value}` : label, keys, href });
		}
		if (filters.query) add($t('Search'), filters.query, ['query']);
		if (filters.project) {
			const selected = project?.id === filters.project ? project : null;
			add(
				$t('Project'),
				selected?.name,
				['project'],
				selected
					? workspaceHref(workspaceId, `projects/${encodeURIComponent(selected.id)}`)
					: undefined
			);
		}
		if (filters.author_last_name !== undefined)
			add(
				$t('Author'),
				[filters.author_last_name, filters.author_first_name].filter(Boolean).join(', '),
				['author_last_name', 'author_first_name']
			);
		if (filters.author) add($t('Contributor'), filters.author, ['author']);
		if (filters.year) add($t('Year'), filters.year, ['year']);
		if (filters.publication_title !== undefined)
			add($t('Publication'), filters.publication_title, ['publication_title']);
		if (filters.reference_type !== undefined)
			add($t('Type'), metadataValueLabel(filters.reference_type), ['reference_type']);
		if (filters.tag) add($t('Tag'), tag.data?.items[0]?.name ?? filters.tag, ['tag']);
		if (filters.keyword_exact !== undefined)
			add($t('Keyword'), filters.keyword_exact, ['keyword_exact']);
		if (filters.keyword) add($t('Keyword'), filters.keyword, ['keyword']);
		if (filters.has_files !== undefined)
			add($t('Files'), filters.has_files ? $t('With files') : $t('Without files'), ['has_files']);
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
			<div class="field-group max-w-full grid-cols-[minmax(0,1fr)_auto] gap-0">
				{#if chip.href}
					<Button as="a" size="sm" class="min-w-0" href={resolve(chip.href)} title={chip.label}
						><span class="truncate">{chip.label}</span></Button
					>
				{/if}
				<Button
					size="sm"
					class="min-w-0"
					onclick={() => onRemove(chip.keys)}
					aria-label={$t('Remove filter {name}', { name: chip.label })}
					title={chip.label}
				>
					<span class="truncate" aria-hidden="true">{chip.href ? '×' : `${chip.label} ×`}</span>
				</Button>
			</div>
		{/each}
	</div>
{/if}
