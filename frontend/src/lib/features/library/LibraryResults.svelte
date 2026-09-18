<script lang="ts">
	import { resolve } from '$app/paths';
	import EmptyState from '$lib/design/EmptyState.svelte';
	import Icon from '$lib/design/Icon.svelte';
	import RichText from '$lib/design/RichText.svelte';
	import type { LibrarySearch } from '$lib/features/library/queries';
	import { t } from '$lib/i18n';

	let {
		data,
		isPending,
		isError,
		pageNumber,
		totalPages,
		allPageSelected,
		selected,
		onTogglePage,
		onToggleItem,
		onPage
	} = $props<{
		data?: LibrarySearch;
		isPending: boolean;
		isError: boolean;
		pageNumber: number;
		totalPages: number;
		allPageSelected: boolean;
		selected: Set<string>;
		onTogglePage: (event: Event) => void;
		onToggleItem: (id: string) => void;
		onPage: (page: number) => void;
	}>();
</script>

<section
	class="mt-6 overflow-hidden rounded-xl border border-surface-300-700 bg-surface-50-950 shadow-sm"
>
	{#if isPending}<div class="grid min-h-56 place-items-center text-surface-600-400">
			{$t('Loading Library…')}
		</div>
	{:else if isError}<div class="grid min-h-56 place-items-center text-error-700-300">
			{$t('Unable to load the Library.')}
		</div>
	{:else if !data?.items.length}<EmptyState
			title={$t('No Items found.')}
			detail={$t('Try a different Library Search.')}
		/>
	{:else}
		<div
			class="bg-surface/60 flex items-center gap-3 border-b border-surface-300-700 px-5 py-3 text-sm"
		>
			<input
				type="checkbox"
				checked={allPageSelected}
				onchange={onTogglePage}
				aria-label={$t('Select this page')}
			/><span class="font-semibold">{$t('Select this page')}</span>
		</div>
		<div class="divide-line divide-y">
			{#each data.items as item (item.id)}
				<article
					class="group grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-5 py-4 transition-colors hover:bg-primary-50-950/60"
				>
					<input
						type="checkbox"
						checked={selected.has(item.id)}
						onchange={() => onToggleItem(item.id)}
						aria-label={`${$t('Select')} ${item.authors ?? ''}`}
					/>
					<a
						class="grid min-w-0 gap-1 no-underline"
						href={resolve('/(app)/item/[itemId]', { itemId: item.id })}
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
		<nav
			class="bg-surface/60 flex items-center justify-center gap-1 border-t border-surface-300-700 px-4 py-3"
			aria-label={$t('Library pages')}
		>
			<button
				type="button"
				class="inline-grid size-9 place-items-center rounded-md border border-surface-300-700 bg-surface-50-950 text-surface-600-400 hover:bg-primary-50-950 hover:text-primary-800-200 disabled:opacity-35"
				disabled={pageNumber <= 1}
				aria-label={$t('First page')}
				title={$t('First page')}
				onclick={() => onPage(1)}><Icon name="chevrons-left" size={17} /></button
			>
			<button
				type="button"
				class="inline-grid size-9 place-items-center rounded-md border border-surface-300-700 bg-surface-50-950 text-surface-600-400 hover:bg-primary-50-950 hover:text-primary-800-200 disabled:opacity-35"
				disabled={pageNumber <= 1}
				aria-label={$t('Previous page')}
				title={$t('Previous page')}
				onclick={() => onPage(pageNumber - 1)}><Icon name="chevron-left" size={17} /></button
			>
			<span class="min-w-24 px-2 text-center text-xs font-medium text-surface-600-400 tabular-nums"
				>{$t('Page')} {pageNumber} {$t('of')} {totalPages}</span
			>
			<button
				type="button"
				class="inline-grid size-9 place-items-center rounded-md border border-surface-300-700 bg-surface-50-950 text-surface-600-400 hover:bg-primary-50-950 hover:text-primary-800-200 disabled:opacity-35"
				disabled={pageNumber >= totalPages}
				aria-label={$t('Next page')}
				title={$t('Next page')}
				onclick={() => onPage(pageNumber + 1)}><Icon name="chevron-right" size={17} /></button
			>
			<button
				type="button"
				class="inline-grid size-9 place-items-center rounded-md border border-surface-300-700 bg-surface-50-950 text-surface-600-400 hover:bg-primary-50-950 hover:text-primary-800-200 disabled:opacity-35"
				disabled={pageNumber >= totalPages}
				aria-label={$t('Last page')}
				title={$t('Last page')}
				onclick={() => onPage(totalPages)}><Icon name="chevrons-right" size={17} /></button
			>
		</nav>
	{/if}
</section>
