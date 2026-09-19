<script lang="ts">
	import type { Snippet } from 'svelte';
	import { t } from '$lib/i18n';

	let { loading, failed, children } = $props<{
		loading: boolean;
		failed: boolean;
		children: Snippet;
	}>();
</script>

{#if loading}
	<div class="grid min-h-52 grid-cols-1 place-items-center text-surface-600-400">
		{$t('Loading')}…
	</div>
{:else if failed}
	<div class="grid min-h-52 grid-cols-1 place-items-center text-error-700-300">
		{$t('Unable to open this Item section.')}
	</div>
{:else}
	{@render children()}
{/if}
