<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import Button from '#lib/design/Button.svelte';
	import { tagsQuery } from '#lib/features/tags/queries.js';
	import { metadataValueLabel } from '#lib/features/item/metadata-labels.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref, type WorkspacePath } from '#lib/workspaces/href.js';
	import { ph, t } from 'lingui-for-svelte/macro';
	import { authorFilterLabel } from './author-names.js';
	import type { LibraryFilters, LibraryAuthorFilter } from './filters.js';
	import type { LibrarySearch } from './queries.js';
	import { orcidId } from '#lib/orcid.js';
	import { rorId } from '#lib/ror.js';

	let {
		filters,
		authors = [],
		project = null,
		onRemove,
		onRemoveAuthor
	}: {
		filters: LibraryFilters;
		authors?: LibrarySearch['items'][number]['authors'];
		project?: { id: string; name: string } | null;
		onRemove: (keys: (keyof LibraryFilters)[]) => void;
		onRemoveAuthor: (author: LibraryAuthorFilter) => void;
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
			author?: LibraryAuthorFilter;
		}[] = [];
		function add(
			label: string,
			value: string | undefined,
			keys: (keyof LibraryFilters)[],
			href?: WorkspacePath
		) {
			result.push({ label: value ? `${label}: ${value}` : label, keys, href });
		}
		if (filters.query) add($t`Search`, filters.query, ['query']);
		if (filters.import_batch)
			add(
				$t`Import Batch`,
				undefined,
				['import_batch'],
				workspaceHref(workspaceId, `import?${new URLSearchParams({ batch: filters.import_batch })}`)
			);
		if (filters.project) {
			const selected = project?.id === filters.project ? project : null;
			add(
				$t`Project`,
				selected?.name,
				['project'],
				selected
					? workspaceHref(workspaceId, `projects/${encodeURIComponent(selected.id)}`)
					: undefined
			);
		}
		for (const author of filters.authors ?? [])
			result.push({
				label: `${$t`Author`}: ${authorFilterLabel(author.last_name, author.first_name ?? undefined, authors)}`,
				keys: ['authors'],
				author
			});
		if (filters.author) add($t`Contributor`, filters.author, ['author']);
		if (filters.author_orcid !== undefined)
			add($t`Author (ORCID)`, filters.author_orcid, ['author_orcid']);
		if (filters.author_ror !== undefined)
			add($t`Author institution (ROR)`, filters.author_ror, ['author_ror']);
		if (filters.year) add($t`Year`, filters.year, ['year']);
		if (filters.publication_title !== undefined)
			add($t`Publication`, filters.publication_title, ['publication_title']);
		if (filters.reference_type !== undefined)
			add($t`Type`, metadataValueLabel(filters.reference_type), ['reference_type']);
		if (filters.tag) add($t`Tag`, tag.data?.items[0]?.name ?? filters.tag, ['tag']);
		if (filters.keyword_exact !== undefined)
			add($t`Keyword`, filters.keyword_exact, ['keyword_exact']);
		if (filters.keyword) add($t`Keyword`, filters.keyword, ['keyword']);
		if (filters.has_files !== undefined)
			add($t`Files`, filters.has_files ? $t`With files` : $t`Without files`, ['has_files']);
		if (filters.has_tags !== undefined)
			add($t`Tag status`, filters.has_tags ? $t`Tagged` : $t`Untagged`, ['has_tags']);
		if (filters.has_projects !== undefined)
			add($t`Project assignment`, filters.has_projects ? $t`With Projects` : $t`Without Projects`, [
				'has_projects'
			]);
		return result;
	});
</script>

{#if chips.length}
	<div class="mt-3 flex flex-wrap items-center gap-2" role="group" aria-label={$t`Applied filters`}>
		{#each chips as chip (chip.author ? JSON.stringify(chip.author) : chip.keys[0])}
			<div class="field-group max-w-full grid-cols-[minmax(0,1fr)_auto] gap-0">
				{#if chip.href}
					<Button as="a" size="sm" class="min-w-0" href={resolve(chip.href)} title={chip.label}
						><span class="truncate">{chip.label}</span></Button
					>
				{/if}
				<Button
					size="sm"
					class="min-w-0"
					onclick={() => (chip.author ? onRemoveAuthor(chip.author) : onRemove(chip.keys))}
					aria-label={$t`Remove filter ${ph({ name: chip.label })}`}
					title={chip.label}
				>
					<span class="truncate" aria-hidden="true">{chip.href ? '×' : `${chip.label} ×`}</span>
				</Button>
			</div>
		{/each}
	</div>
{/if}

{#if filters.author_orcid !== undefined}
	<p class="mt-2 text-xs text-surface-600-400">
		{#if orcidId(filters.author_orcid)}
			{$t`Only Items with this ORCID saved on a personal Author credit are included.`}
			{#if filters.author_ror === undefined && (filters.author || filters.authors?.length)}
				{$t`Name and ORCID filters may match different authors on the same Item.`}
			{/if}
		{:else}
			{$t`Invalid ORCID filter. Remove it to continue.`}
		{/if}
	</p>
{/if}

{#if filters.author_ror !== undefined}
	<p class="mt-2 text-xs text-surface-600-400">
		{#if rorId(filters.author_ror)}
			{$t`Only saved RORs on Author affiliations or organizational Author credits are included.`}
			{#if filters.author_orcid !== undefined}
				{$t`ORCID, ROR and name filters may match different authors on the same Item.`}
			{:else if filters.author || filters.authors?.length}
				{$t`Name and ROR filters may match different authors on the same Item.`}
			{/if}
		{:else}{$t`Invalid ROR filter. Remove it to continue.`}{/if}
	</p>
{/if}
