<script lang="ts">
	import Button from '#lib/design/Button.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import { t } from '#lib/i18n.js';

	let {
		message,
		busy = false,
		onRetry
	}: {
		message: string;
		busy?: boolean;
		onRetry: () => void;
	} = $props();
</script>

<Notice as="div" variant="error" class="my-3 flex flex-wrap items-center justify-between gap-3">
	<span>{message}</span>
	<Button type="button" disabled={busy} onclick={onRetry}>{$t('Retry')}</Button>
</Notice>
