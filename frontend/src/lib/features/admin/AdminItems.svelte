<script lang="ts">
	import { resolve } from '$app/paths';
	import type { ItemSummary } from '$lib/api/client';
	import Panel from '$lib/design/Panel.svelte';
	import RichText from '$lib/design/RichText.svelte';
	import { t } from '$lib/i18n';
	import Button from '$lib/design/Button.svelte';
	import ItemRow from '$lib/design/ItemRow.svelte';

	let { items, busy, onDelete } = $props<{
		items: { items: ItemSummary[]; total: number; storage: { total_disk_bytes: number } };
		busy: boolean;
		onDelete: (itemId: string) => void;
	}>();
</script>

<Panel class="mt-4">
	<h2>{$t('Items')} ({items.total})</h2>
	<p class="text-surface-600-400">
		{Math.ceil(items.storage.total_disk_bytes / 1048576)} MB stored
	</p>
	{#each items.items as item (item.id)}
		<ItemRow class="grid-cols-[minmax(0,1fr)_auto] items-center">
			<a
				class="grid grid-cols-1 gap-1 no-underline"
				href={resolve('/(app)/item/[itemId]', { itemId: item.id })}
				><strong><RichText html={item.title_html} /></strong><span class="text-surface-600-400"
					>{item.authors ?? $t('Unknown authors')}</span
				></a
			><Button variant="danger" disabled={busy} onclick={() => onDelete(item.id)}
				>{$t('Delete')}</Button
			>
		</ItemRow>
	{:else}
		<p class="text-surface-600-400">{$t('No Items.')}</p>
	{/each}
</Panel>
