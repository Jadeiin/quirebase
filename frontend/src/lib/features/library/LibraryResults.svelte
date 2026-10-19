<script lang="ts">
	import { resolve } from '$app/paths';
	import EmptyState from '#lib/design/EmptyState.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import RichText from '#lib/design/RichText.svelte';
	import type { LibrarySearch } from '#lib/features/library/queries.js';
	import { t } from '#lib/i18n.js';
	import { workspaceHref } from '#lib/workspaces/href.js';

	let {
		data,
		workspaceId,
		isPending,
		isError,
		pageNumber,
		pageSize,
		sort,
		busy,
		totalPages,
		allPageSelected,
		selected,
		onTogglePage,
		onToggleItem,
		onPage,
		onPageSize,
		onSort,
		onRetry
	}: {
		data?: LibrarySearch;
		workspaceId: string;
		isPending: boolean;
		isError: boolean;
		pageNumber: number;
		pageSize: number;
		sort: string;
		busy: boolean;
		totalPages: number;
		allPageSelected: boolean;
		selected: Set<string>;
		onTogglePage: (event: Event) => void;
		onToggleItem: (id: string) => void;
		onPage: (page: number) => void;
		onPageSize: (size: number) => void;
		onSort: (sort: string) => void;
		onRetry: () => void;
	} = $props();
</script>

<Panel padding="none" class="mt-6">
	{#if isPending}<div class="grid min-h-56 grid-cols-1 place-items-center text-surface-600-400">
			{$t('Loading Library…')}
		</div>
	{:else if isError}<QueryError message={$t('Unable to load the Library.')} {busy} {onRetry} />
	{:else if !data?.items.length}<EmptyState
			title={$t('No Items found.')}
			detail={$t('Try a different Library Search.')}
		/>
	{:else}
		<div
			class="flex items-center gap-3 border-b border-surface-300-700 bg-surface-100-900 px-5 py-3 text-sm"
		>
			<input
				type="checkbox"
				checked={allPageSelected}
				onchange={onTogglePage}
				aria-label={$t('Select this page')}
			/><span class="font-semibold">{$t('Select this page')}</span>
		</div>
		<div class="divide-y divide-surface-300-700">
			{#each data.items as item (item.id)}
				<article
					class="group grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-5 py-4 transition-colors hover:bg-primary-50-950/60"
				>
					<input
						type="checkbox"
						checked={selected.has(item.id)}
						onchange={() => onToggleItem(item.id)}
						aria-label={item.authors ? $t('Select {name}', { name: item.authors }) : $t('Select')}
					/>
					<a
						class="grid min-w-0 grid-cols-1 gap-1 no-underline"
						href={resolve(workspaceHref(workspaceId, `item/${item.id}`))}
						><strong class="text-[0.98rem] leading-snug group-hover:text-primary-800-200"
							><RichText html={item.title_html} /></strong
						><span class="truncate text-sm text-surface-600-400"
							>{item.authors || $t('Unknown authors')}</span
						>{#if item.publication_title}<span class="truncate text-xs text-surface-600-400"
								>{item.publication_title}</span
							>{/if}</a
					>
					<span class="flex items-center gap-2 text-xs text-surface-600-400"
						>{item.publication_date || '—'}<Icon name="chevron-right" size={16} /></span
					>
				</article>
			{/each}
		</div>
	{/if}
	<Pagination
		page={pageNumber}
		pageCount={totalPages}
		{pageSize}
		total={data?.total ?? 0}
		{sort}
		sortOptions={[
			{ value: 'updated', label: $t('Recently updated') },
			{ value: 'created', label: $t('Recently added') },
			{ value: 'title', label: $t('Title') }
		]}
		{busy}
		label={$t('Library pages')}
		{onPage}
		{onPageSize}
		{onSort}
	/>
</Panel>
