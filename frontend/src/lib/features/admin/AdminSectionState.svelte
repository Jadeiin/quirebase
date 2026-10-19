<script lang="ts">
	import LoadingState from '#lib/design/LoadingState.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import type { Snippet } from 'svelte';
	import { t, type MessageKey } from '#lib/i18n.js';

	let {
		loading,
		failed,
		label,
		busy = false,
		onRetry,
		children
	}: {
		loading: boolean;
		failed: boolean;
		label: MessageKey;
		busy?: boolean;
		onRetry: () => void;
		children: Snippet;
	} = $props();
</script>

{#if loading}
	<LoadingState label={$t('Loading {section}…', { section: $t(label) })} />
{:else if failed}
	<QueryError message={$t('Unable to load administration.')} {busy} {onRetry} />
{:else}
	{@render children()}
{/if}
