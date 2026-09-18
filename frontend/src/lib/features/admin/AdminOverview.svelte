<script lang="ts">
	import ItemRow from '$lib/design/ItemRow.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import Stat from '$lib/design/Stat.svelte';
	import { t } from '$lib/i18n';
	import type { components } from '$lib/api/schema';

	let { overview } = $props<{ overview: components['schemas']['AdminOverviewView'] }>();
</script>

<div class="grid grid-cols-2 gap-3 min-[800px]:grid-cols-4">
	<Stat value={overview.user_count} label={$t('Users')} />
	<Stat value={overview.pending_invitation_count} label={$t('Pending invitations')} />
	<Stat value={overview.storage.items_count} label={$t('Items')} />
	<Stat value={overview.failed_workflows.length} label={$t('Failed workflows')} />
</div>
<Panel class="mt-4">
	<h2>{$t('Recent audit events')}</h2>
	{#each overview.recent_events as event (event.id)}
		<ItemRow>
			<strong>{event.action}</strong><span class="text-surface-600-400"
				>{event.target_type} · {new Date(event.created_at).toLocaleString()}</span
			>
		</ItemRow>
	{:else}
		<p class="text-surface-600-400">{$t('No audit events.')}</p>
	{/each}
</Panel>
