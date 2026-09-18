<script lang="ts">
	import { t } from '$lib/i18n';
	import type { components } from '$lib/api/schema';

	let { overview } = $props<{ overview: components['schemas']['AdminOverviewView'] }>();
</script>

<div class="stat-grid admin-stats">
	<div><strong>{overview.user_count}</strong><span>{$t('Users')}</span></div>
	<div>
		<strong>{overview.pending_invitation_count}</strong><span>{$t('Pending invitations')}</span>
	</div>
	<div><strong>{overview.storage.items_count}</strong><span>{$t('Items')}</span></div>
	<div>
		<strong>{overview.failed_workflows.length}</strong><span>{$t('Failed workflows')}</span>
	</div>
</div>
<section class="list-panel card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
	<h2>{$t('Recent audit events')}</h2>
	{#each overview.recent_events as event (event.id)}
		<div class="item-row">
			<strong>{event.action}</strong><span class="text-surface-600-400"
				>{event.target_type} · {new Date(event.created_at).toLocaleString()}</span
			>
		</div>
	{:else}
		<p class="text-surface-600-400">{$t('No audit events.')}</p>
	{/each}
</section>
