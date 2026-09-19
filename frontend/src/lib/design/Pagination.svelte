<script lang="ts">
	import Button from '$lib/design/Button.svelte';
	import { t } from '$lib/i18n';

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

<nav class={`flex items-center justify-center gap-3 pt-4 ${className}`.trim()} aria-label={label}>
	<Button disabled={busy || page <= 1} onclick={() => onPage(page - 1)}>{$t('Previous')}</Button>
	<span>{$t('Page {page} of {pageCount}', { page, pageCount })}</span>
	<Button disabled={busy || page >= pageCount} onclick={() => onPage(page + 1)}>{$t('Next')}</Button
	>
</nav>
