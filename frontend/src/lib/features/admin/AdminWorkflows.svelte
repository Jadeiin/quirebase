<script lang="ts">
	import Panel from '$lib/design/Panel.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';
	import type { components } from '$lib/api/schema';
	import ItemRow from '$lib/design/ItemRow.svelte';

	let { workflows } = $props<{ workflows: components['schemas']['WorkflowSummaryView'][] }>();
</script>

<Panel class="mt-4">
	<h2>{$t('Durable workflows')}</h2>
	{#each workflows as workflow (workflow.id)}
		<ItemRow>
			<strong>{workflow.name || workflow.id || $t('Workflow')}</strong><span
				class="text-surface-600-400"
				>{$t(domainLabel(workflow.state))}{workflow.error ? ` · ${workflow.error}` : ''}</span
			>
		</ItemRow>
	{:else}
		<p class="text-surface-600-400">{$t('No workflows.')}</p>
	{/each}
</Panel>
