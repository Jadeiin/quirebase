<script lang="ts">
	import { resolve } from '$app/paths';
	import { Progress } from '@skeletonlabs/skeleton-svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import Icon from '#lib/design/Icon.svelte';
	import { getWorkflowCenter, type TrackedJob } from '#lib/features/workflows/center.svelte.js';
	import {
		isRecoverableWorkflowStatusError,
		isTerminalWorkflowState,
		workflowStatusQuery
	} from '#lib/features/workflows/queries.js';
	import { t } from 'lingui-for-svelte/macro';
	import Button from '#lib/design/Button.svelte';
	import { workspaceHref } from '#lib/workspaces/href.js';

	let {
		job,
		visible = true,
		onNavigate
	}: { job: TrackedJob; visible?: boolean; onNavigate?: () => void } = $props();
	const center = getWorkflowCenter();
	const status = createQuery(() => ({
		...workflowStatusQuery(job.workspaceId, job.id, () => !job.outcome && !job.unavailable),
		enabled: !job.outcome && !job.unavailable
	}));
	const state = $derived(job.outcome?.state ?? status.data?.state);

	$effect(() => {
		if (job.outcome || job.unavailable) return;
		const current = status.data;
		// Settle outside the reaction update: writing center state from inside this
		// effect corrupts Svelte's dependency bookkeeping when the flush was entered
		// through a Zag callback (popover positioning).
		if (current && isTerminalWorkflowState(current.state)) {
			const terminal = current;
			const id = job.id;
			queueMicrotask(() => center.resolve(id, terminal));
		} else if (status.isError && status.error && !isRecoverableWorkflowStatusError(status.error)) {
			// A missing or inaccessible status record cannot establish the business outcome.
			const id = job.id;
			queueMicrotask(() => center.markUnavailable(id));
		}
	});
</script>

{#if visible}
	<div class="flex items-center gap-3 px-4 py-3">
		<span
			class={[
				'size-2.5 shrink-0 rounded-full',
				state === 'succeeded' && 'bg-success-500',
				(state === 'failed' || state === 'cancelled') && 'bg-error-500',
				job.unavailable
					? 'bg-surface-500'
					: !state || !isTerminalWorkflowState(state)
						? 'bg-primary-500'
						: ''
			]}
			aria-hidden="true"
		></span>
		<div class="grid min-w-0 flex-1 grid-cols-1 gap-0.5">
			<strong class="truncate text-sm">{job.label}</strong>
			<span class="text-xs text-surface-600-400">
				{#if job.unavailable}{$t`Workflow history is unavailable. Check the current result.`}{:else if job.outcome}{job
						.outcome.state}{#if job.outcome.error}: {job.outcome
							.error}{/if}{:else if status.data}{status.data.state}{#if status.data.error}:
						{status.data.error}{/if}{:else}{$t`Starting…`}{/if}
			</span>
			{#if !job.unavailable && (!state || !isTerminalWorkflowState(state))}
				<Progress value={null} aria-label={job.label}>
					<Progress.Track class="h-1"
						><Progress.Range
							class="bg-primary-700-300 motion-reduce:animate-none"
						/></Progress.Track
					>
				</Progress>
			{/if}
			{#if job.workspaceId && job.target?.kind === 'import_batch'}
				<a
					class="w-fit anchor text-xs"
					href={resolve(
						workspaceHref(
							job.workspaceId,
							`import?${new URLSearchParams({ batch: job.target.id })}`
						)
					)}
					onclick={(event) => {
						if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey)
							onNavigate?.();
					}}>{$t`View import`}</a
				>
			{/if}
		</div>
		<Button
			variant="icon"
			class="shrink-0"
			type="button"
			aria-label={$t`Dismiss`}
			onclick={() => center.dismiss(job.id)}><Icon name="close" size={14} /></Button
		>
	</div>
{/if}
