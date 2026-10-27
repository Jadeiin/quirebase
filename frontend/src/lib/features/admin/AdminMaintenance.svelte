<script lang="ts">
	import Panel from '#lib/design/Panel.svelte';
	import { dateTimeFormat, megabytes, numberFormat } from '#lib/format.js';
	import { ph, plural, t } from 'lingui-for-svelte/macro';
	import type { MessageDescriptor } from '@lingui/core';
	import type { components } from '#lib/api/schema.js';
	import Button from '#lib/design/Button.svelte';

	type Operation = 'check_objects';

	let {
		maintenance,
		operations,
		busy,
		onRun
	}: {
		maintenance: components['schemas']['StorageMetricsView'];
		operations: ReadonlyArray<readonly [Operation, MessageDescriptor]>;
		busy: boolean;
		onRun: (operation: Operation) => void;
	} = $props();

	let removedRecords = $derived(
		Object.values(maintenance.cleanup_counts ?? {}).reduce((sum, count) => sum + count, 0)
	);
	let integrityErrors = $derived(maintenance.integrity_errors ?? []);
</script>

<Panel class="grid grid-cols-1 gap-3">
	<h2>{$t`Maintenance`}</h2>
	<p>
		{$plural({ count: maintenance.items_count }, { one: '# Item', other: '# Items' })} · {$t`${ph({ size: $numberFormat.format(megabytes(maintenance.total_disk_bytes)) })} MB`}
	</p>
	<dl class="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
		<dt>{$t`Database allocation`}</dt>
		<dd>
			{$t`${ph({ size: $numberFormat.format(megabytes(maintenance.database_allocated_bytes)) })} MB`}
		</dd>
		{#if maintenance.database_reusable_bytes != null}
			<dt>{$t`Reusable database space`}</dt>
			<dd>
				{$t`${ph({ size: $numberFormat.format(megabytes(maintenance.database_reusable_bytes)) })} MB`}
			</dd>
		{/if}
		<dt>{$t`Workflow history`}</dt>
		<dd>{maintenance.workflow_history_count ?? '—'}</dd>
		<dt>{$t`Workflow checkpoints`}</dt>
		<dd>{maintenance.workflow_checkpoint_count ?? '—'}</dd>
		<dt>{$t`Transaction checkpoints`}</dt>
		<dd>{maintenance.datasource_checkpoint_count ?? '—'}</dd>
		<dt>{$t`Object integrity`}</dt>
		<dd>
			{#if maintenance.integrity_status === 'failed'}
				{$t`Failed`}
			{:else if maintenance.integrity_checked_at}
				{$dateTimeFormat.format(new Date(maintenance.integrity_checked_at))}
				· {$plural(
					{ count: maintenance.integrity_error_count ?? 0 },
					{ one: '# error', other: '# errors' }
				)}
			{:else}
				{$t`Not checked`}
			{/if}
		</dd>
		<dt>{$t`Automatic cleanup`}</dt>
		<dd>
			{#if maintenance.cleanup_error}
				{$t`Failed`} ({maintenance.cleanup_error})
			{:else if maintenance.cleanup_checked_at}
				{$dateTimeFormat.format(new Date(maintenance.cleanup_checked_at))}
				· {$t`Removed ${ph({ count: removedRecords })} records`}
			{:else if maintenance.cleanup_started_at}
				{$t`Running`}
			{:else}
				{$t`Not run yet`}
			{/if}
		</dd>
	</dl>
	{#if integrityErrors.length}
		<details>
			<summary>{$t`Integrity error samples`}</summary>
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
</Panel>
