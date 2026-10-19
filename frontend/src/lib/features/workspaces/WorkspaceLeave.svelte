<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { ApiError } from '#lib/api/client.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceKeys } from '#lib/workspaces/keys.js';
	import {
		clearDefaultWorkspacePreference,
		defaultWorkspacePreference
	} from '#lib/workspaces/preference.js';
	import { getSession } from '#lib/session.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Panel from '#lib/design/Panel.svelte';
	import Button from '#lib/design/Button.svelte';
	import ConfirmDialog from '#lib/design/ConfirmDialog.svelte';
	import { t } from '#lib/i18n.js';
	import { reconcileWorkspaceAccessLoss } from './access-loss.js';
	import { workspaceLeaveMutationOptions } from './mutations';

	const workspace = getWorkspaceContext();
	const session = getSession().query;
	const client = useQueryClient();
	const mutation = createMutation(() => workspaceLeaveMutationOptions(workspace.workspaceId));
	let open = $state(false);
	let target = $state<{ membershipId: string; name: string } | null>(null);
	let settling = $state(false);
	let error = $state('');
	const busy = $derived(mutation.isPending || settling);

	async function leave() {
		if (busy || !target) return;
		const { workspaceId, api } = workspace;
		const userId = session.data?.user?.id ?? '';
		error = '';
		settling = true;
		try {
			await mutation.mutateAsync(target.membershipId);
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to leave workspace.'));
			// This command-owned read survives route/query observer teardown. It checks
			// the captured Workspace directly without replaying an uncertain leave.
			let unavailable = false;
			try {
				const view = await api.request('GET', '/workspaces/{workspace_id}');
				client.setQueryData(workspaceKeys.root(workspaceId), view);
			} catch (reason) {
				unavailable = reason instanceof ApiError && reason.code === 'workspace_unavailable';
			}
			if (!unavailable) {
				settling = false;
				return;
			}
		}
		if (defaultWorkspacePreference() === workspaceId) clearDefaultWorkspacePreference();
		// Finishing an operation must not pull the user out of a different Workspace.
		if (page.params.workspaceId === workspaceId)
			await goto(resolve('workspace'), { replace: true });
		await reconcileWorkspaceAccessLoss(client, workspaceId, userId);
		open = false;
		settling = false;
	}
</script>

<Panel class="grid grid-cols-1 justify-items-start gap-3">
	<h2 class="text-xl font-semibold">{$t('Leave workspace')}</h2>
	<p class="text-sm text-surface-700-300">
		{$t(
			'Leaving removes your access. Existing workspace content and your contributions are kept. You will need a new invitation to rejoin.'
		)}
	</p>
	{#if workspace.can('workspace_member.leave')}
		<Button
			variant="danger"
			disabled={busy}
			onclick={() => {
				target = {
					membershipId: workspace.view!.current_membership_id,
					name: workspace.view!.name
				};
				error = '';
				open = true;
			}}>{$t('Leave workspace')}</Button
		>
	{:else if workspace.view?.governance_frozen || workspace.view?.state === 'archived'}
		<p class="text-sm text-surface-700-300">
			{$t('You cannot leave while this workspace is read only.')}
		</p>
	{:else}
		<p class="text-sm text-surface-700-300">
			{$t('Transfer workspace ownership to another member before leaving.')}
		</p>
	{/if}
</Panel>

<ConfirmDialog
	bind:open
	title={$t('Leave workspace')}
	body={$t(
		'Leave {name}? You will lose access to its library and projects. Your contributions will remain in the workspace.',
		{ name: target?.name ?? '' }
	)}
	confirmLabel={$t('Leave workspace')}
	{busy}
	{error}
	onConfirm={() => void leave()}
/>
