<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { getWorkflowCenter } from '#lib/features/workflows/center.svelte.js';
	import Button from '#lib/design/Button.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import StatusNotice from '#lib/design/StatusNotice.svelte';
	import ConfirmDialog from '#lib/design/ConfirmDialog.svelte';
	import PromptDialog from '#lib/design/PromptDialog.svelte';
	import { msg, t } from '#lib/i18n.js';
	import { workspaceLifecycleMutationOptions, workspaceReindexMutationOptions } from './mutations';

	const workspace = getWorkspaceContext();
	const client = useQueryClient();
	const workflows = getWorkflowCenter();
	const lifecycle = createMutation(() =>
		workspaceLifecycleMutationOptions(workspace.workspaceId, client)
	);
	const maintenance = createMutation(() => workspaceReindexMutationOptions(workspace.workspaceId));
	const busy = $derived(lifecycle.isPending || maintenance.isPending);
	let archiveOpen = $state(false);
	let deleteOpen = $state(false);
	let error = $state('');
	let notice = $state('');
	let maintenanceError = $state('');
	let maintenanceNotice = $state('');
	const hasLifecycle = $derived(
		workspace.can('workspace.archive') ||
			workspace.can('workspace.restore') ||
			workspace.can('workspace.delete')
	);

	async function changeLifecycle(action: 'archive' | 'restore' | 'delete') {
		if (busy) return;
		error = '';
		notice = '';
		try {
			await lifecycle.mutateAsync(action);
			archiveOpen = false;
			deleteOpen = false;
			if (action === 'delete') {
				await goto(resolve('workspace'), { replace: true });
				return;
			}
			notice = action === 'archive' ? $t('Workspace archived') : $t('Workspace restored');
		} catch (reason) {
			error = apiErrorMessage(reason, 'Workspace action failed');
		}
	}
	async function reindex() {
		if (busy) return;
		maintenanceError = '';
		maintenanceNotice = '';
		try {
			const started = await maintenance.mutateAsync();
			void workflows
				.track(started.id, {
					workspaceId: workspace.workspaceId,
					label: $t('Workspace reindex'),
					successMessage: msg('Workspace reindex completed'),
					failureMessage: msg('Workspace reindex failed')
				})
				.settled.catch(() => undefined);
			maintenanceNotice = $t('Workspace reindex started');
		} catch (reason) {
			maintenanceError = apiErrorMessage(reason, 'Workspace action failed');
		}
	}
</script>

<section class="grid grid-cols-1 gap-6" aria-labelledby="workspace-advanced-heading">
	<div>
		<h2 id="workspace-advanced-heading" class="text-xl font-semibold">{$t('Advanced')}</h2>
		<p class="mt-1 text-sm text-surface-700-300">
			{$t('Maintenance and lifecycle actions for this workspace.')}
		</p>
	</div>
	{#if workspace.can('workspace_maintenance.run')}
		<Panel class="grid grid-cols-1 justify-items-start gap-3">
			<h3 class="text-lg font-semibold">{$t('Workspace maintenance')}</h3>
			<p class="text-sm text-surface-700-300">{$t('Rebuild search indexes for this Workspace.')}</p>
			<Button disabled={busy} onclick={() => void reindex()}>{$t('Reindex Workspace')}</Button>
			<StatusNotice error={maintenanceError} notice={maintenanceNotice} />
		</Panel>
	{/if}
	{#if hasLifecycle}
		<Panel class="grid grid-cols-1 justify-items-start gap-3">
			<h3 class="text-lg font-semibold">{$t('Lifecycle')}</h3>
			<p class="text-sm text-surface-700-300">
				{$t(
					'Archive pauses normal changes while preserving readable content. You can restore it later.'
				)}
			</p>
			{#if workspace.can('workspace.archive') && workspace.view?.state === 'active'}
				<Button
					variant="warning"
					disabled={busy}
					onclick={() => {
						error = '';
						archiveOpen = true;
					}}>{$t('Archive workspace')}</Button
				>
			{/if}
			{#if workspace.can('workspace.restore') && workspace.view?.state === 'archived'}
				<Button variant="success" disabled={busy} onclick={() => void changeLifecycle('restore')}
					>{$t('Restore workspace')}</Button
				>
			{/if}
			<StatusNotice error={archiveOpen || deleteOpen ? '' : error} {notice} />
		</Panel>
	{/if}
	{#if workspace.can('workspace.delete')}
		<Panel class="grid grid-cols-1 justify-items-start gap-3 border-error-500/40">
			<h3 class="text-lg font-semibold">{$t('Permanent deletion')}</h3>
			<p class="text-sm text-surface-700-300">
				{$t(
					'This permanently removes the workspace and its content after the archive retention period. This cannot be undone.'
				)}
			</p>
			<Button
				variant="danger-filled"
				disabled={busy || workspace.view?.state !== 'archived'}
				onclick={() => {
					error = '';
					deleteOpen = true;
				}}>{$t('Permanently delete workspace')}</Button
			>
		</Panel>
	{/if}
	{#if !hasLifecycle && !workspace.can('workspace_maintenance.run')}<Notice
			>{$t('No advanced actions are available for this workspace.')}</Notice
		>{/if}
</section>

<ConfirmDialog
	bind:open={archiveOpen}
	title={$t('Archive workspace')}
	body={$t('Archive {name}? Members will retain read access to its content.', {
		name: workspace.view?.name ?? ''
	})}
	confirmLabel={$t('Archive workspace')}
	{busy}
	{error}
	onConfirm={() => void changeLifecycle('archive')}
/>
<PromptDialog
	bind:open={deleteOpen}
	title={$t('Permanently delete workspace')}
	body={$t('Permanently delete {name} and its content? This cannot be undone.', {
		name: workspace.view?.name ?? ''
	})}
	label={$t('Type the workspace name to confirm')}
	requireMatch={workspace.view?.name ?? ''}
	confirmLabel={$t('Permanently delete workspace')}
	{busy}
	{error}
	onConfirm={() => void changeLifecycle('delete')}
/>
