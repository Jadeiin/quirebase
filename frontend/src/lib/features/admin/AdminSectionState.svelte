<script lang="ts">
	import LoadingState from '#lib/design/LoadingState.svelte';
	import type { Snippet } from 'svelte';
	import { t, type MessageKey } from '#lib/i18n.js';

	let { loading, failed, label, children } = $props<{
		loading: boolean;
		failed: boolean;
		label: MessageKey;
		children: Snippet;
	}>();
</script>

{#if loading}
	<LoadingState label={$t('Loading {section}…', { section: $t(label) })} />
{:else if failed}
	<p class="text-error-700-300">{$t('Unable to load administration.')}</p>
{:else}
	{@render children()}
{/if}
