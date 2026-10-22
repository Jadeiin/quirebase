<script lang="ts">
	import { Pagination } from '@skeletonlabs/skeleton-svelte';
	import { buttonClass } from '#lib/design/button-classes.js';
	import Icon from '#lib/design/Icon.svelte';
	import { t } from '#lib/i18n.js';

	let {
		page,
		pageCount,
		pageSize,
		pageSizeOptions = [10, 20, 25, 50, 100],
		total,
		onPage,
		onPageSize,
		sort,
		sortOptions = [],
		onSort,
		label,
		busy = false,
		class: className = ''
	}: {
		page: number;
		pageCount: number;
		pageSize: number;
		pageSizeOptions?: number[];
		total: number;
		onPage: (page: number) => void;
		onPageSize: (pageSize: number) => void;
		sort?: string;
		sortOptions?: { value: string; label: string }[];
		onSort?: (sort: string) => void;
		label: string;
		busy?: boolean;
		class?: string;
	} = $props();

	const triggerClass = `${buttonClass('icon', 'sm')} size-8 shrink-0`;
	const pageSizes = $derived([...new Set([...pageSizeOptions, pageSize])].sort((a, b) => a - b));
	const start = $derived(total === 0 ? 0 : Math.min((page - 1) * pageSize + 1, total));
	const end = $derived(Math.min(page * pageSize, total));
</script>

<nav
	class={`flex flex-wrap items-center justify-center gap-x-6 gap-y-3 border-t border-surface-300-700 bg-surface-100-900 px-3 py-3 sm:justify-between sm:px-4 ${className}`.trim()}
	aria-label={label}
	aria-busy={busy}
>
	<div
		class="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-xs text-surface-700-300"
	>
		<label class="flex items-center gap-2 whitespace-nowrap">
			{$t('Page Size')}
			<select
				class="select h-8 w-auto field-xs"
				value={pageSize}
				disabled={busy}
				onchange={(event) => {
					const next = Number(event.currentTarget.value);
					// Keep the displayed page's size until its owner applies the new value.
					event.currentTarget.value = String(pageSize);
					onPageSize(next);
				}}
			>
				{#each pageSizes as size (size)}<option value={size}>{size}</option>{/each}
			</select>
		</label>
		{#if onSort && sortOptions.length}
			<label class="flex items-center gap-2 whitespace-nowrap">
				{$t('Sort By')}
				<select
					class="select h-8 w-auto max-w-52 field-xs"
					value={sort}
					disabled={busy}
					onchange={(event) => onSort?.(event.currentTarget.value)}
				>
					{#each sortOptions as option (option.value)}
						<option value={option.value}>{option.label}</option>
					{/each}
				</select>
			</label>
		{/if}
		<span class="whitespace-nowrap tabular-nums" aria-live="polite">
			{$t('Showing {start}–{end} of {total}', { start, end, total })}
		</span>
	</div>
	<Pagination
		{page}
		count={total}
		{pageSize}
		onPageChange={(details) => onPage(details.page)}
		class="flex items-center justify-center gap-1 rounded-none border-0 p-0"
	>
		<Pagination.FirstTrigger
			type="button"
			class={triggerClass}
			disabled={busy || page <= 1}
			aria-label={$t('First page')}
			title={$t('First page')}
		>
			<Icon name="chevrons-left" size={17} />
		</Pagination.FirstTrigger>
		<Pagination.PrevTrigger
			class={triggerClass}
			disabled={busy || page <= 1}
			aria-label={$t('Previous page')}
			title={$t('Previous page')}
		>
			<Icon name="chevron-left" size={17} />
		</Pagination.PrevTrigger>
		<span
			class="min-w-0 px-2 text-center text-xs font-medium text-surface-700-300 tabular-nums sm:min-w-24"
			aria-live="polite"
		>
			{$t('Page {page} of {pageCount}', { page, pageCount })}
		</span>
		<Pagination.NextTrigger
			class={triggerClass}
			disabled={busy || page >= pageCount}
			aria-label={$t('Next page')}
			title={$t('Next page')}
		>
			<Icon name="chevron-right" size={17} />
		</Pagination.NextTrigger>
		<Pagination.LastTrigger
			type="button"
			class={triggerClass}
			disabled={busy || page >= pageCount}
			aria-label={$t('Last page')}
			title={$t('Last page')}
		>
			<Icon name="chevrons-right" size={17} />
		</Pagination.LastTrigger>
	</Pagination>
</nav>
