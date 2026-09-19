<script lang="ts">
	import type { Snippet } from 'svelte';
	import { t, type MessageKey } from '$lib/i18n';

	let { loading, failed, label, children } = $props<{
		loading: boolean;
		failed: boolean;
		label: MessageKey;
		children: Snippet;
	}>();
</script>

{#if loading}
	<p class="text-surface-600-400">{$t('Loading {section}…', { section: $t(label) })}</p>
{:else if failed}
	<p class="text-error-700-300">{$t('Unable to load administration.')}</p>
{:else}
	{@render children()}
{/if}
