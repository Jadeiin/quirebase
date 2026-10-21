<script lang="ts">
	import type { components } from '#lib/api/schema.js';
	import Badge from '#lib/design/Badge.svelte';
	import Button from '#lib/design/Button.svelte';
	import DataTable from '#lib/design/DataTable.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { dateTimeFormat, numberFormat } from '#lib/format.js';
	import { t } from '#lib/i18n.js';

	type Workspace = components['schemas']['AdminWorkspaceView'];
	let {
		workspaces,
		total,
		busy = false,
		refreshing = false,
		reassignmentId,
		onRefresh,
		onReassign,
		onGovern
	}: {
		workspaces: Workspace[];
		total: number;
		busy?: boolean;
		refreshing?: boolean;
		reassignmentId?: string;
		onRefresh: () => void;
		onReassign: (workspace: Workspace) => void;
		onGovern: (workspace: Workspace, operation: 'freeze' | 'unfreeze') => void;
	} = $props();
</script>

{#snippet actions()}
	<Button type="button" size="sm" disabled={refreshing} onclick={onRefresh}>{$t('Refresh')}</Button>
{/snippet}

<Panel padding="none" class="min-w-0">
	<SectionHeader class="px-5 pt-5" spacing="compact" {actions}>
		<h2>
			{$t('Workspaces')}
			<span class="text-base font-normal text-surface-600-400">{$numberFormat.format(total)}</span>
		</h2>
	</SectionHeader>
	{#if workspaces.length}
		<DataTable label={$t('Workspaces')}>
			<thead
				><tr>
					<th scope="col">{$t('Workspace')}</th>
					<th scope="col">{$t('Owner')}</th>
					<th scope="col">{$t('State')}</th>
					<th scope="col">{$t('Write freeze')}</th>
					<th scope="col">{$t('Created')}</th>
					<th scope="col">{$t('Actions')}</th>
				</tr></thead
			>
			{#each workspaces as workspace (workspace.id)}
				<tbody aria-label={workspace.name}>
					<tr>
						<th scope="row" class="font-normal"
							><div class="min-w-0">
								<strong>{workspace.name}</strong>
								<p class="mt-1 text-xs text-surface-600-400">{workspace.id}</p>
							</div></th
						>
						<td data-label={$t('Owner')}
							><div class="min-w-0">
								<span>{workspace.owner_username}</span>
								{#if !workspace.owner_active}<div class="mt-1">
										<Badge variant="warning">{$t('Owner account disabled')}</Badge>
									</div>{/if}
							</div></td
						>
						<td data-label={$t('State')}><Badge>{$t(domainLabel(workspace.state))}</Badge></td>
						<td data-label={$t('Write freeze')}
							><div class="min-w-0">
								{#if workspace.governance_frozen_at}
									<Badge variant="warning">{$t('read-only freeze')}</Badge>
									<time
										class="mt-1 block text-xs text-surface-600-400"
										datetime={workspace.governance_frozen_at}
										>{$dateTimeFormat.format(new Date(workspace.governance_frozen_at))}</time
									>
								{:else}{$t('Not frozen')}{/if}
							</div></td
						>
						<td data-label={$t('Created')}
							><time datetime={workspace.created_at}
								>{$dateTimeFormat.format(new Date(workspace.created_at))}</time
							></td
						>
						<td data-label={$t('Actions')}
							><div class="flex flex-wrap gap-2">
								{#if workspace.can_reassign_owner}<Button
										type="button"
										size="sm"
										class="h-auto whitespace-normal"
										disabled={busy}
										aria-expanded={reassignmentId === workspace.id}
										onclick={() => onReassign(workspace)}>{$t('Reassign owner')}</Button
									>{/if}
								<Button
									type="button"
									size="sm"
									class="h-auto whitespace-normal"
									disabled={busy}
									onclick={() =>
										onGovern(workspace, workspace.governance_frozen_at ? 'unfreeze' : 'freeze')}
									>{workspace.governance_frozen_at
										? $t('Unfreeze writes')
										: $t('Freeze writes')}</Button
								>
							</div></td
						>
					</tr>
				</tbody>
			{/each}
		</DataTable>
	{:else}<p class="px-5 pb-5 text-surface-600-400">{$t('No matching workspaces.')}</p>{/if}
</Panel>
