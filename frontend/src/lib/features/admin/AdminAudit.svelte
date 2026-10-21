<script lang="ts">
	import Badge from '#lib/design/Badge.svelte';
	import Button from '#lib/design/Button.svelte';
	import DataTable from '#lib/design/DataTable.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import { dateTimeFormat } from '#lib/format.js';
	import { t } from '#lib/i18n.js';
	import type { components } from '#lib/api/schema.js';

	let {
		events,
		onRefresh,
		busy = false
	}: {
		events: components['schemas']['AdminAuditEventView'][];
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
		<h2>{$t('Audit log')}</h2>
	</SectionHeader>
	{#if events.length}
		<DataTable label={$t('Audit log')}>
			<thead>
				<tr>
					<th scope="col">{$t('Date')}</th>
					<th scope="col">{$t('Action')}</th>
					<th scope="col">{$t('Target type')}</th>
					<th scope="col">{$t('Result')}</th>
					<th scope="col"><span class="sr-only">{$t('Details')}</span></th>
				</tr>
			</thead>
			{#each events as event (event.id)}
				<tbody aria-label={`${event.action} · ${event.id}`}>
					<tr>
						<td data-label={$t('Date')}>
							<time datetime={event.created_at} class="text-sm"
								>{$dateTimeFormat.format(new Date(event.created_at))}</time
							>
						</td>
						<td data-label={$t('Action')}><strong>{event.action}</strong></td>
						<td data-label={$t('Target type')}>{event.target_type}</td>
						<td data-label={$t('Result')}
							>{#if event.result}<Badge>{event.result}</Badge>{:else}—{/if}</td
						>
						<td data-label={$t('Details')}>
							<Button
								type="button"
								size="sm"
								aria-expanded={expandedId === event.id}
								aria-controls={`${id}-${event.id}`}
								onclick={() => (expandedId = expandedId === event.id ? null : event.id)}
								>{$t('Details')}</Button
							>
						</td>
					</tr>
					{#if expandedId === event.id}
						<tr>
							<td colspan="5">
								<div id={`${id}-${event.id}`} data-audit-details class="grid grid-cols-1 gap-4">
									<dl class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
										<div>
											<dt>{$t('Event ID')}</dt>
											<dd>{event.id}</dd>
										</div>
										{#if event.actor_id}<div>
												<dt>{$t('Actor ID')}</dt>
												<dd>{event.actor_id}</dd>
											</div>{/if}
										{#if event.target_id}<div>
												<dt>{$t('Target ID')}</dt>
												<dd>{event.target_id}</dd>
											</div>{/if}
										{#if event.workspace_id}<div>
												<dt>{$t('Workspace ID')}</dt>
												<dd>{event.workspace_id}</dd>
											</div>{/if}
										{#if event.project_id}<div>
												<dt>{$t('Project ID')}</dt>
												<dd>{event.project_id}</dd>
											</div>{/if}
										{#if event.authorization_role}<div>
												<dt>{$t('Authorization role')}</dt>
												<dd>{event.authorization_role}</dd>
											</div>{/if}
										{#if event.authorization_resource_action}<div>
												<dt>{$t('Authorization action')}</dt>
												<dd>{event.authorization_resource_action}</dd>
											</div>{/if}
										{#if event.source}<div>
												<dt>{$t('Source')}</dt>
												<dd>{event.source}</dd>
											</div>{/if}
									</dl>
									{#if event.target_ids?.length}
										<div>
											<h3 class="mb-2 text-sm font-medium">{$t('Target IDs')}</h3>
											<ul class="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
												{#each event.target_ids as targetId, index (index)}<li>
														{targetId}
													</li>{/each}
											</ul>
										</div>
									{/if}
									{#if event.detail != null}
										<div>
											<h3 class="mb-2 text-sm font-medium">{$t('Event detail')}</h3>
											<pre
												class="max-h-80 overflow-y-auto rounded bg-surface-200-800 p-3 text-xs">{typeof event.detail ===
												'string'
													? event.detail
													: JSON.stringify(event.detail, null, 2)}</pre>
										</div>
									{/if}
								</div>
							</td>
						</tr>
					{/if}
				</tbody>
			{/each}
		</DataTable>
	{:else}
		<p class="px-5 pb-5 text-surface-600-400">{$t('No audit events.')}</p>
	{/if}
</Panel>

<style>
	[data-audit-details] {
		overflow-wrap: anywhere;
	}
	[data-audit-details] dt {
		color: var(--color-surface-600-400);
	}
	[data-audit-details] dd {
		margin-top: 0.25rem;
	}
	[data-audit-details] pre {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
</style>
