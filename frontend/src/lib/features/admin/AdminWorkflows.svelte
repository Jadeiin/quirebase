<script lang="ts">
	import Panel from '#lib/design/Panel.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import Badge from '#lib/design/Badge.svelte';
	import Button from '#lib/design/Button.svelte';
	import DataTable from '#lib/design/DataTable.svelte';
	import { dateTimeFormat } from '#lib/format.js';
	import { domainLabel } from '#lib/domain-labels.js';
	import { t } from '#lib/i18n.js';
	import type { components } from '#lib/api/schema.js';
	import AdminWorkflowDetail from './AdminWorkflowDetail.svelte';

	let {
		workflows,
		onRefresh,
		busy = false
	}: {
		workflows: components['schemas']['WorkflowSummaryView'][];
		onRefresh?: () => void;
		busy?: boolean;
	} = $props();
	let expandedId = $state<string | null>(null);
	const id = $props.id();
</script>

{#snippet refreshAction()}<Button type="button" size="sm" disabled={busy} onclick={onRefresh}
		>{$t('Refresh')}</Button
	>{/snippet}

<Panel class="mt-4 min-w-0" padding="none">
	<SectionHeader
		class="px-5 pt-5"
		spacing="compact"
		actions={onRefresh ? refreshAction : undefined}
	>
		<h2>{$t('Durable workflows')}</h2>
	</SectionHeader>
	{#if workflows.length}
		<DataTable label={$t('Durable workflows')}>
			<thead>
				<tr>
					<th scope="col">{$t('Workflow')}</th>
					<th scope="col">{$t('State')}</th>
					<th scope="col">{$t('Created')}</th>
					<th scope="col">{$t('Updated')}</th>
					<th scope="col"><span class="sr-only">{$t('Details')}</span></th>
				</tr>
			</thead>
			{#each workflows as workflow (workflow.id)}
				<tbody aria-label={workflow.name || workflow.id}>
					<tr>
						<td data-label={$t('Workflow')}><strong>{workflow.name || workflow.id}</strong></td>
						<td data-label={$t('State')}>
							<Badge
								variant={workflow.state === 'succeeded'
									? 'success'
									: workflow.state === 'failed'
										? 'error'
										: 'surface'}>{$t(domainLabel(workflow.state))}</Badge
							>
						</td>
						<td data-label={$t('Created')}>
							{#if workflow.created_at}<time datetime={workflow.created_at} class="text-sm"
									>{$dateTimeFormat.format(new Date(workflow.created_at))}</time
								>{:else}—{/if}
						</td>
						<td data-label={$t('Updated')}>
							{#if workflow.updated_at}<time datetime={workflow.updated_at} class="text-sm"
									>{$dateTimeFormat.format(new Date(workflow.updated_at))}</time
								>{:else}—{/if}
						</td>
						<td data-label={$t('Details')}>
							<Button
								type="button"
								size="sm"
								aria-expanded={expandedId === workflow.id}
								aria-controls={`${id}-${workflow.id}`}
								onclick={() => (expandedId = expandedId === workflow.id ? null : workflow.id)}
								>{$t('Details')}</Button
							>
						</td>
					</tr>
					{#if expandedId === workflow.id}
						<tr
							><td colspan="5"
								><div id={`${id}-${workflow.id}`}>
									<AdminWorkflowDetail workflowId={workflow.id} />
								</div></td
							></tr
						>
					{/if}
				</tbody>
			{/each}
		</DataTable>
	{:else}
		<p class="px-5 pb-5 text-surface-600-400">{$t('No workflows.')}</p>
	{/if}
</Panel>
