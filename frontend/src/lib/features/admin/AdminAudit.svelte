<script lang="ts">
	import { t } from '$lib/i18n';
	import type { components } from '$lib/api/schema';

	let { events } = $props<{ events: components['schemas']['AdminAuditEventView'][] }>();
</script>

<section class="list-panel card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
	<h2>{$t('Audit log')}</h2>
	{#each events as event (event.id)}
		<div class="item-row">
			<strong>{event.action}</strong><span
				>{event.target_type}{event.target_id ? ` · ${event.target_id}` : ''}</span
			><span class="text-surface-600-400"
				>{event.actor_id ? `${$t('Actor')} ${event.actor_id} · ` : ''}{new Date(
					event.created_at
				).toLocaleString()}</span
			>
			{#if event.detail}
				<pre class="overflow-x-auto rounded bg-surface-200-800 p-2 text-xs">{typeof event.detail ===
					'string'
						? event.detail
						: JSON.stringify(event.detail, null, 2)}</pre>
			{/if}
		</div>
	{:else}
		<p class="text-surface-600-400">{$t('No audit events.')}</p>
	{/each}
</section>
