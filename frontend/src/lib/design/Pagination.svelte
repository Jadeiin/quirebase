<script lang="ts">
	import Icon from '#lib/design/Icon.svelte';
	import { t } from '#lib/i18n.js';

	let {
		page,
		pageCount,
		onPage,
		label,
		busy = false,
		class: className = ''
	} = $props<{
		page: number;
		pageCount: number;
		onPage: (page: number) => void;
		label: string;
		busy?: boolean;
		class?: string;
	}>();
</script>

<nav
	class={`flex min-w-0 items-center justify-center gap-1 border-t border-surface-300-700 bg-surface-100-900 px-2 py-3 sm:px-4 ${className}`.trim()}
	aria-label={label}
>
	<button
		type="button"
		class="inline-grid size-9 shrink-0 cursor-pointer place-items-center rounded-md border border-surface-300-700 bg-surface-50-950 text-surface-600-400 hover:bg-primary-50-950 hover:text-primary-800-200 disabled:cursor-not-allowed disabled:opacity-35"
		disabled={busy || page <= 1}
		aria-label={$t('First page')}
		title={$t('First page')}
		onclick={() => onPage(1)}><Icon name="chevrons-left" size={17} /></button
	>
	<button
		type="button"
		class="inline-grid size-9 shrink-0 cursor-pointer place-items-center rounded-md border border-surface-300-700 bg-surface-50-950 text-surface-600-400 hover:bg-primary-50-950 hover:text-primary-800-200 disabled:cursor-not-allowed disabled:opacity-35"
		disabled={busy || page <= 1}
		aria-label={$t('Previous page')}
		title={$t('Previous page')}
		onclick={() => onPage(page - 1)}><Icon name="chevron-left" size={17} /></button
	>
	<span
		class="min-w-0 px-2 text-center text-xs font-medium text-surface-600-400 tabular-nums sm:min-w-24"
		>{$t('Page {page} of {pageCount}', { page, pageCount })}</span
	>
	<button
		type="button"
		class="inline-grid size-9 shrink-0 cursor-pointer place-items-center rounded-md border border-surface-300-700 bg-surface-50-950 text-surface-600-400 hover:bg-primary-50-950 hover:text-primary-800-200 disabled:cursor-not-allowed disabled:opacity-35"
		disabled={busy || page >= pageCount}
		aria-label={$t('Next page')}
		title={$t('Next page')}
		onclick={() => onPage(page + 1)}><Icon name="chevron-right" size={17} /></button
	>
	<button
		type="button"
		class="inline-grid size-9 shrink-0 cursor-pointer place-items-center rounded-md border border-surface-300-700 bg-surface-50-950 text-surface-600-400 hover:bg-primary-50-950 hover:text-primary-800-200 disabled:cursor-not-allowed disabled:opacity-35"
		disabled={busy || page >= pageCount}
		aria-label={$t('Last page')}
		title={$t('Last page')}
		onclick={() => onPage(pageCount)}><Icon name="chevrons-right" size={17} /></button
	>
</nav>
