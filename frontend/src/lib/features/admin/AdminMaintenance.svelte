<script lang="ts">
	import Panel from '#lib/design/Panel.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { dateTimeFormat, megabytes, numberFormat } from '#lib/format.js';
	import { t, type MessageKey } from '#lib/i18n.js';
	import type { components } from '#lib/api/schema.js';
	import Button from '#lib/design/Button.svelte';
	import ItemRow from '#lib/design/ItemRow.svelte';

	type Workflow = components['schemas']['WorkflowSummaryView'];
	type Operation = 'check_objects';

	let {
		maintenance,
		operations,
		busy,
		onRun
	}: {
		maintenance: {
			storage: components['schemas']['StorageMetricsView'];
			workflows: Workflow[];
		};
		operations: ReadonlyArray<readonly [Operation, MessageKey]>;
		busy: boolean;
		onRun: (operation: Operation) => void;
	} = $props();

	let removedRecords = $derived(
		Object.values(maintenance.storage.cleanup_counts ?? {}).reduce((sum, count) => sum + count, 0)
	);
	let integrityErrors = $derived(maintenance.storage.integrity_errors ?? []);
</script>

<Panel class="grid grid-cols-1 gap-3">
	<h2>{$t('Maintenance')}</h2>
	<p>
		{$t('{count, plural, one {# Item} other {# Items}}', {
			count: maintenance.storage.items_count
		})} · {$t('{size} MB', {
			size: $numberFormat.format(megabytes(maintenance.storage.total_disk_bytes))
		})}
	</p>
	<dl class="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
		<dt>{$t('Database allocation')}</dt>
		<dd>
			{$t('{size} MB', {
				size: $numberFormat.format(megabytes(maintenance.storage.database_allocated_bytes))
			})}
		</dd>
		{#if maintenance.storage.database_reusable_bytes != null}
			<dt>{$t('Reusable database space')}</dt>
			<dd>
				{$t('{size} MB', {
					size: $numberFormat.format(megabytes(maintenance.storage.database_reusable_bytes))
				})}
			</dd>
		{/if}
		<dt>{$t('Workflow history')}</dt>
		<dd>{maintenance.storage.workflow_history_count ?? '—'}</dd>
		<dt>{$t('Workflow checkpoints')}</dt>
		<dd>{maintenance.storage.workflow_checkpoint_count ?? '—'}</dd>
		<dt>{$t('Transaction checkpoints')}</dt>
		<dd>{maintenance.storage.datasource_checkpoint_count ?? '—'}</dd>
		<dt>{$t('Object integrity')}</dt>
		<dd>
			{#if maintenance.storage.integrity_status === 'failed'}
				{$t('Failed')}
			{:else if maintenance.storage.integrity_checked_at}
				{$dateTimeFormat.format(new Date(maintenance.storage.integrity_checked_at))}
				· {$t('{count, plural, one {# error} other {# errors}}', {
					count: maintenance.storage.integrity_error_count ?? 0
				})}
			{:else}
				{$t('Not checked')}
			{/if}
		</dd>
		<dt>{$t('Automatic cleanup')}</dt>
		<dd>
			{#if maintenance.storage.cleanup_error}
				{$t('Failed')} ({maintenance.storage.cleanup_error})
			{:else if maintenance.storage.cleanup_checked_at}
				{$dateTimeFormat.format(new Date(maintenance.storage.cleanup_checked_at))}
				· {$t('Removed {count} records', { count: removedRecords })}
			{:else if maintenance.storage.cleanup_started_at}
				{$t('Running')}
			{:else}
				{$t('Not run yet')}
			{/if}
		</dd>
	</dl>
	{#if integrityErrors.length}
		<details>
			<summary>{$t('Integrity error samples')}</summary>
			<ul class="mt-2 max-h-48 overflow-auto text-sm">
				{#each integrityErrors as error, index (index)}
					<li class="break-all">{error}</li>
				{/each}
			</ul>
		</details>
	{/if}
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
		</ItemRow>
	{:else}
		<p class="text-surface-600-400">{$t('No maintenance workflows.')}</p>
	{/each}
</Panel>
