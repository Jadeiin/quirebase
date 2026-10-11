<script lang="ts">
	import { Pagination } from '@skeletonlabs/skeleton-svelte';
	import { buttonClass } from '#lib/design/button-classes.js';
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

	const triggerClass = buttonClass('icon', 'sm');
</script>

<nav
	class={`border-t border-surface-300-700 bg-surface-100-900 px-2 py-3 sm:px-4 ${className}`.trim()}
	aria-label={label}
>
	<Pagination
		{page}
		count={pageCount}
		pageSize={1}
		onPageChange={(details) => onPage(details.page)}
		class="flex w-full items-center justify-center gap-1 rounded-none border-0 p-0"
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
			class="min-w-0 px-2 text-center text-xs font-medium text-surface-600-400 tabular-nums sm:min-w-24"
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
