<script lang="ts">
	import Panel from '$lib/design/Panel.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t, type MessageKey } from '$lib/i18n';
	import type { components } from '$lib/api/schema';
	import Button from '$lib/design/Button.svelte';
	import ItemRow from '$lib/design/ItemRow.svelte';

	type Workflow = components['schemas']['WorkflowSummaryView'];
	type Operation = 'reindex_all' | 'check_objects' | 'backup' | 'recommend_tags_all';

	let { maintenance, operations, busy, onRun, onDownloadBackup } = $props<{
		maintenance: {
			storage: { items_count: number; total_disk_bytes: number };
			workflows: Workflow[];
		};
		operations: ReadonlyArray<readonly [Operation, MessageKey]>;
		busy: boolean;
		onRun: (operation: Operation) => void;
		onDownloadBackup: (workflowId: string) => void;
	}>();
</script>

<Panel class="grid grid-cols-1 gap-3">
	<h2>{$t('Maintenance')}</h2>
	<p>
		{maintenance.storage.items_count} Items · {Math.ceil(
			maintenance.storage.total_disk_bytes / 1048576
		)} MB
	</p>
	<div class="flex flex-wrap gap-2">
		{#each operations as [operation, label] (operation)}
			<Button disabled={busy} onclick={() => onRun(operation)}>{$t(label)}</Button>
		{/each}
	</div>
	<h3>{$t('Recent operations')}</h3>
	{#each maintenance.workflows as workflow (workflow.id)}
		<ItemRow>
			<strong>{workflow.name || workflow.id || $t('Operation')}</strong><span
				class="text-surface-600-400">{$t(domainLabel(workflow.state))}</span
			>
			{#if workflow.state === 'succeeded' && (workflow.name ?? '').includes('backup') && workflow.id}
				<Button onclick={() => onDownloadBackup(workflow.id)}>{$t('Download backup')}</Button>
			{/if}
		</ItemRow>
	{:else}
		<p class="text-surface-600-400">{$t('No maintenance workflows.')}</p>
	{/each}
</Panel>
