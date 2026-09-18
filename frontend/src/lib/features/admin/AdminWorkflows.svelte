<script lang="ts">
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';
	import type { components } from '$lib/api/schema';

	let { workflows } = $props<{ workflows: components['schemas']['WorkflowSummaryView'][] }>();
</script>

<section class="list-panel card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
	<h2>{$t('Durable workflows')}</h2>
	{#each workflows as workflow (workflow.id)}
		<div class="item-row">
			<strong>{workflow.name || workflow.id || $t('Workflow')}</strong><span
				class="text-surface-600-400"
				>{$t(domainLabel(workflow.state))}{workflow.error ? ` · ${workflow.error}` : ''}</span
			>
		</div>
	{:else}
		<p class="text-surface-600-400">{$t('No workflows.')}</p>
	{/each}
</section>
