<script lang="ts">
	import { resolve } from '$app/paths';
	import type { ItemSummary } from '$lib/api/client';
	import RichText from '$lib/design/RichText.svelte';
	import { t } from '$lib/i18n';

	let { items, busy, onDelete } = $props<{
		items: { items: ItemSummary[]; total: number; storage: { total_disk_bytes: number } };
		busy: boolean;
		onDelete: (itemId: string) => void;
	}>();
</script>

<section class="list-panel card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
	<h2>{$t('Items')} ({items.total})</h2>
	<p class="text-surface-600-400">
		{Math.ceil(items.storage.total_disk_bytes / 1048576)} MB stored
	</p>
	{#each items.items as item (item.id)}
		<div class="item-row grid-cols-[minmax(0,1fr)_auto] items-center">
			<a class="grid gap-1 no-underline" href={resolve('/(app)/item/[itemId]', { itemId: item.id })}
				><strong><RichText html={item.title_html} /></strong><span class="text-surface-600-400"
					>{item.authors ?? $t('Unknown authors')}</span
				></a
			><button
				class="btn preset-tonal-error font-semibold"
				disabled={busy}
				onclick={() => onDelete(item.id)}>{$t('Delete')}</button
			>
		</div>
	{:else}
		<p class="text-surface-600-400">{$t('No Items.')}</p>
	{/each}
</section>
