<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery } from '@tanstack/svelte-query';
	import Button from '#lib/design/Button.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import { metadataValueLabel } from '#lib/features/item/metadata-labels.js';
	import { ph, t } from 'lingui-for-svelte/macro';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { libraryFacetsQuery } from './queries.js';
	import {
		sameAuthor,
		type LibraryFilters,
		type LibraryMetadataFilter,
		type libraryHref
	} from './filters.js';

	let {
		filters,
		pageNumber,
		pageSize,
		filterHref
	}: {
		filters: LibraryFilters;
		pageNumber: number;
		pageSize: number;
		filterHref: (filter: LibraryMetadataFilter) => ReturnType<typeof libraryHref>;
	} = $props();
	const { workspaceId } = getWorkspaceContext();
	const facets = createQuery(() => libraryFacetsQuery(workspaceId, filters, pageNumber, pageSize));
	let expanded = $state<Record<string, boolean>>({});
	const listId = $props.id();
	function isSelected(filter: LibraryMetadataFilter) {
		const author = 'authors' in filter ? filter.authors[0] : undefined;
		return author && filters.authors?.some((name) => sameAuthor(name, author));
	}

	type Choice = { label: string; count: number; filter: LibraryMetadataFilter };
	const groups = $derived<{ key: string; label: string; choices: Choice[] }[]>([
		{
			key: 'authors',
			label: $t`Author`,
			choices: (facets.data?.authors ?? []).map((author) => ({
				label: author.full_name,
				count: author.item_count,
				filter: { authors: [{ last_name: author.last_name, first_name: author.first_name ?? '' }] }
			}))
		},
		{
			key: 'keywords',
			label: $t`Keyword`,
			choices: (facets.data?.keywords ?? []).map((keyword) => ({
				label: keyword.value,
				count: keyword.item_count,
				filter: { keyword_exact: keyword.value }
			}))
		},
		{
			key: 'types',
			label: $t`Type`,
			choices: (facets.data?.reference_types ?? []).map((type) => ({
				label: metadataValueLabel(type.value),
				count: type.item_count,
				filter: { reference_type: type.value }
			}))
		}
	]);
</script>

<section aria-label={$t`Refine current results`} class="border-t border-surface-300-700 pt-4">
	<h2 class="text-sm font-semibold">{$t`Refine current results`}</h2>
	<p class="mt-1 text-xs text-surface-600-400">
		{$t`Filter Items by author, keyword and type.`}
	</p>
	{#if facets.isError || facets.fetchStatus === 'paused' || facets.data === null}
		<QueryError
			message={$t`Unable to load filter values.`}
			busy={facets.isFetching}
			onRetry={() => void facets.refetch()}
		/>
	{/if}
	{#if facets.data}
		<div class="mt-3 grid grid-cols-1 gap-4 md:grid-cols-3">
			{#each groups as group (group.key)}
				<div role="group" aria-label={group.label} class="min-w-0">
					<h3 class="mb-2 text-xs font-semibold text-surface-600-400">{group.label}</h3>
					<ul
						id={`${listId}-${group.key}`}
						class="grid grid-cols-1 gap-1"
						class:max-h-80={Boolean(expanded[group.key])}
						class:overflow-y-auto={Boolean(expanded[group.key])}
					>
						{#each expanded[group.key] ? group.choices : group.choices.slice(0, 5) as choice (JSON.stringify(choice.filter))}
							<li class="min-w-0">
								<a
									href={resolve(filterHref(choice.filter))}
									title={choice.label}
									aria-current={isSelected(choice.filter) ? 'true' : undefined}
									class="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 rounded-base px-2 py-1.5 text-sm no-underline hover:bg-surface-100-900 aria-[current=true]:bg-primary-100-900 aria-[current=true]:font-semibold"
								>
									<span class="line-clamp-2 min-w-0 wrap-anywhere">{choice.label}</span><span
										class="min-w-6 pt-0.5 text-right text-xs text-surface-600-400 tabular-nums"
										>{choice.count}</span
									>
								</a>
							</li>
						{:else}
							<li class="text-xs text-surface-600-400">{$t`No values on this page.`}</li>
						{/each}
					</ul>
					{#if group.choices.length > 5}
						<Button
							type="button"
							size="sm"
							class="mt-2"
							aria-expanded={Boolean(expanded[group.key])}
							aria-controls={`${listId}-${group.key}`}
							aria-label={expanded[group.key]
								? $t`Show less ${ph({ field: group.label })}`
								: $t`Show more ${ph({ field: group.label })}`}
							onclick={() => (expanded[group.key] = !expanded[group.key])}
							>{expanded[group.key] ? $t`Show less` : $t`Show more`}</Button
						>
					{/if}
				</div>
			{/each}
		</div>
	{:else if facets.isPending && facets.fetchStatus !== 'paused'}
		<p role="status" class="mt-3 text-sm text-surface-600-400">{$t`Loading filter values…`}</p>
	{/if}
</section>
