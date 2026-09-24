<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { apiErrorMessage } from '$lib/api/errors';
	import Icon from '$lib/design/Icon.svelte';
	import { getWorkflowCenter, type TrackedJob } from '$lib/features/workflows/center.svelte';
	import {
		isRecoverableWorkflowStatusError,
		isTerminalWorkflowState,
		workflowStatusQuery
	} from '$lib/features/workflows/queries';
	import { t } from '$lib/i18n';
	import Button from '$lib/design/Button.svelte';

	let { job, visible = true } = $props<{ job: TrackedJob; visible?: boolean }>();
	const center = getWorkflowCenter();
	const status = createQuery(() =>
		workflowStatusQuery(job.workspaceId, job.id, () => !job.outcome)
	);
	const state = $derived(job.outcome?.state ?? status.data?.state);

	$effect(() => {
		if (job.outcome) return;
		const current = status.data;
		// Settle outside the reaction update: writing center state from inside this
		// effect corrupts Svelte's dependency bookkeeping when the flush was entered
		// through a Zag callback (popover positioning).
		if (current && isTerminalWorkflowState(current.state)) {
			const terminal = current;
			const id = job.id;
			queueMicrotask(() => center.resolve(id, terminal));
		} else if (status.isError && status.error && !isRecoverableWorkflowStatusError(status.error)) {
			// A failed status request is terminal for this client-side tracker
			// when the API reports a permanent error. Transport, timeout, rate
			// limit, and server errors stay active so refetchInterval can recover.
			const message = apiErrorMessage(status.error, job.failureMessage);
			const id = job.id;
			queueMicrotask(() => center.fail(id, message));
		}
	});
</script>

{#if visible}
	<div class="flex items-center gap-3 px-4 py-3">
		<span
			class={[
				'size-2.5 shrink-0 rounded-full',
				state === 'succeeded' && 'bg-success-500-500',
				(state === 'failed' || state === 'cancelled') && 'bg-error-500-500',
				!state || !isTerminalWorkflowState(state) ? 'bg-primary-500-500 animate-pulse' : ''
			]}
			aria-hidden="true"
		></span>
		<div class="grid min-w-0 flex-1 grid-cols-1 gap-0.5">
			<strong class="truncate text-sm">{job.label}</strong>
			<span class="text-xs text-surface-600-400">
				{#if job.outcome}{job.outcome.state}{#if job.outcome.error}: {job.outcome
							.error}{/if}{:else if status.data}{status.data.state}{#if status.data.error}:
						{status.data.error}{/if}{:else}{$t('Starting…')}{/if}
			</span>
		</div>
		<Button
			variant="icon"
			class="shrink-0"
			type="button"
			aria-label={$t('Dismiss')}
			onclick={() => center.dismiss(job.id)}><Icon name="close" size={14} /></Button
		>
	</div>
{/if}
