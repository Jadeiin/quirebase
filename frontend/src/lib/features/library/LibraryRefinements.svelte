<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import Button from '#lib/design/Button.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import { metadataValueLabel } from '#lib/features/item/metadata-labels.js';
	import { t } from '#lib/i18n.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { libraryFacetsQuery } from './queries.js';
	import type { LibraryFilters, LibraryMetadataFilter, libraryHref } from './filters.js';

	let {
		filters,
		filterHref
	}: {
		filters: LibraryFilters;
		filterHref: (filter: LibraryMetadataFilter) => ReturnType<typeof libraryHref>;
	} = $props();
	const { workspaceId } = getWorkspaceContext();
	const facets = createQuery(() => libraryFacetsQuery(workspaceId, filters));
	let expanded = $state<Record<string, boolean>>({});
	type Choice = { label: string; count: number; filter: LibraryMetadataFilter };
	const groups = $derived<{ key: string; label: string; choices: Choice[] }[]>([
		{
			key: 'authors',
			label: $t('Author'),
			choices: (facets.data?.authors ?? []).map((author) => ({
				label: [author.last_name, author.first_name].filter(Boolean).join(', '),
				count: author.item_count,
				filter: { author_last_name: author.last_name, author_first_name: author.first_name ?? '' }
			}))
		},
		{
			key: 'keywords',
			label: $t('Keyword'),
			choices: (facets.data?.keywords ?? []).map((keyword) => ({
				label: keyword.value,
				count: keyword.item_count,
				filter: { keyword_exact: keyword.value }
			}))
		},
		{
			key: 'types',
			label: $t('Type'),
			choices: (facets.data?.reference_types ?? []).map((type) => ({
				label: metadataValueLabel(type.value),
				count: type.item_count,
				filter: { reference_type: type.value }
			}))
		}
	]);
</script>

<section aria-label={$t('Refine current results')} class="border-t border-surface-300-700 pt-4">
	<h2 class="text-sm font-semibold">{$t('Refine current results')}</h2>
	<p class="mt-1 text-xs text-surface-600-400">
		{$t(
			'Most frequent values in the applied results, up to 50 per field. Counts reflect Items, not occurrences.'
		)}
	</p>
	{#if facets.isError || facets.fetchStatus === 'paused' || facets.data === null}
		<QueryError
			message={$t('Unable to load filter values.')}
			busy={facets.isFetching}
			onRetry={() => void facets.refetch()}
		/>
	{/if}
	{#if facets.data}
		<div class="mt-3 grid grid-cols-1 gap-4 md:grid-cols-3">
			{#each groups as group (group.key)}
				<div role="group" aria-label={group.label} class="min-w-0">
					<h3 class="mb-2 text-xs font-semibold text-surface-600-400">{group.label}</h3>
					<ul class="grid grid-cols-1 gap-1">
						{#each group.choices.slice(0, expanded[group.key] ? 50 : 5) as choice (JSON.stringify(choice.filter))}
							<li class="min-w-0">
								<a
									href={resolve(filterHref(choice.filter))}
									title={choice.label}
									class="flex min-w-0 items-center justify-between gap-2 rounded-base px-2 py-1.5 text-sm no-underline hover:bg-surface-100-900"
								>
									<span class="truncate">{choice.label}</span><span
										class="shrink-0 text-xs text-surface-600-400 tabular-nums">{choice.count}</span
									>
								</a>
							</li>
						{:else}
							<li class="text-xs text-surface-600-400">{$t('No values in these results.')}</li>
						{/each}
					</ul>
					{#if group.choices.length > 5}
						<Button
							type="button"
							size="sm"
							class="mt-2"
							aria-expanded={Boolean(expanded[group.key])}
							onclick={() => (expanded[group.key] = !expanded[group.key])}
							>{expanded[group.key] ? $t('Show less') : $t('Show more')}</Button
						>
					{/if}
				</div>
			{/each}
		</div>
	{:else if facets.isPending && facets.fetchStatus !== 'paused'}
		<p role="status" class="mt-3 text-sm text-surface-600-400">{$t('Loading filter values…')}</p>
	{/if}
</section>
