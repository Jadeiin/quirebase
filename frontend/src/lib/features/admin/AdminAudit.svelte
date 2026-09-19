<script lang="ts">
	import Panel from '$lib/design/Panel.svelte';
	import { dateTimeFormat } from '$lib/format';
	import { t } from '$lib/i18n';
	import type { components } from '$lib/api/schema';
	import ItemRow from '$lib/design/ItemRow.svelte';

	let { events } = $props<{ events: components['schemas']['AdminAuditEventView'][] }>();
</script>

<Panel class="mt-4">
	<h2>{$t('Audit log')}</h2>
	{#each events as event (event.id)}
		<ItemRow>
			<strong>{event.action}</strong><span
				>{event.target_type}{event.target_id ? ` · ${event.target_id}` : ''}</span
			><span class="text-surface-600-400"
				>{event.actor_id
					? `${$t('Actor: {actor}', { actor: event.actor_id })} · `
					: ''}{$dateTimeFormat.format(new Date(event.created_at))}</span
			>
			{#if event.detail}
				<pre class="overflow-x-auto rounded bg-surface-200-800 p-2 text-xs">{typeof event.detail ===
					'string'
						? event.detail
						: JSON.stringify(event.detail, null, 2)}</pre>
			{/if}
		</ItemRow>
	{:else}
		<p class="text-surface-600-400">{$t('No audit events.')}</p>
	{/each}
</Panel>
