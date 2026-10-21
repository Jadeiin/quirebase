<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Button from '#lib/design/Button.svelte';
	import LoadingState from '#lib/design/LoadingState.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { t } from '#lib/i18n.js';
	import { adminWorkflowDetailQuery } from './queries.js';
	import { isAdminUnavailableError } from './read-state.js';

	let { workflowId }: { workflowId: string } = $props();
	const detail = createQuery(() => adminWorkflowDetailQuery(workflowId));
	const workflow = $derived(isAdminUnavailableError(detail.error) ? null : detail.data);
	const failed = $derived(detail.isError || workflow === null);
</script>

<div data-workflow-details class="min-w-0" aria-busy={detail.isFetching}>
	{#if failed}
		<QueryError
			message={apiErrorMessage(detail.error, $t('Unable to load workflow details.'))}
			busy={detail.isFetching}
			onRetry={() => void detail.refetch()}
		/>
	{/if}
	{#if workflow}
		<dl class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
			<div>
				<dt>{$t('Workflow ID')}</dt>
				<dd>{workflow.id}</dd>
			</div>
			<div>
				<dt>{$t('State')}</dt>
				<dd>{$t(domainLabel(workflow.state))}</dd>
			</div>
			<div>
				<dt>{$t('Raw status')}</dt>
				<dd>{workflow.raw_status}</dd>
			</div>
			{#if workflow.queue_name}<div>
					<dt>{$t('Queue')}</dt>
					<dd>{workflow.queue_name}</dd>
				</div>{/if}
			{#if workflow.executor_id}<div>
					<dt>{$t('Executor ID')}</dt>
					<dd>{workflow.executor_id}</dd>
				</div>{/if}
			{#if workflow.authenticated_user}<div>
					<dt>{$t('Authenticated user')}</dt>
					<dd>{workflow.authenticated_user}</dd>
				</div>{/if}
		</dl>
		{#if workflow.error}
			<h3 class="mt-4 mb-2 text-sm font-medium">{$t('Error')}</h3>
			<pre
				class="max-h-80 overflow-y-auto rounded bg-surface-200-800 p-3 text-xs">{workflow.error}</pre>
		{/if}
		{#if workflow.output != null}
			<h3 class="mt-4 mb-2 text-sm font-medium">{$t('Output')}</h3>
			<pre
				class="max-h-80 overflow-y-auto rounded bg-surface-200-800 p-3 text-xs">{typeof workflow.output ===
				'string'
					? workflow.output
					: JSON.stringify(workflow.output, null, 2)}</pre>
		{/if}
		{#if workflow.attributes && Object.keys(workflow.attributes).length}
			<h3 class="mt-4 mb-2 text-sm font-medium">{$t('Attributes')}</h3>
			<pre class="max-h-80 overflow-y-auto rounded bg-surface-200-800 p-3 text-xs">{JSON.stringify(
					workflow.attributes,
					null,
					2
				)}</pre>
		{/if}
		<Button
			class="mt-4"
			type="button"
			size="sm"
			disabled={detail.isFetching}
			onclick={() => void detail.refetch()}>{$t('Refresh details')}</Button
		>
	{:else if !failed}
		<LoadingState
			label={detail.fetchStatus === 'paused'
				? $t('Waiting for a connection.')
				: $t('Loading workflow details…')}
		/>
	{/if}
</div>

<style>
	[data-workflow-details] {
		overflow-wrap: anywhere;
	}
	[data-workflow-details] dt {
		color: var(--color-surface-600-400);
	}
	[data-workflow-details] dd {
		margin-top: 0.25rem;
	}
	[data-workflow-details] pre {
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
</style>
