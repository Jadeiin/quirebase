<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import type { components } from '#lib/api/schema.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { domainLabel } from '#lib/domain-labels.js';
	import { dateFormat } from '#lib/format.js';
	import Button from '#lib/design/Button.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import StatusNotice from '#lib/design/StatusNotice.svelte';
	import { t } from '#lib/i18n.js';
	import { workspaceInvitationsQuery } from './queries';
	import {
		workspaceInvitationMutationOptions,
		workspaceInvitationRevokeMutationOptions
	} from './mutations';

	const workspace = getWorkspaceContext();
	const client = useQueryClient();
	const invitations = createQuery(() => ({
		...workspaceInvitationsQuery(workspace.workspaceId),
		enabled: workspace.can('workspace_invitation.read')
	}));
	const create = createMutation(() =>
		workspaceInvitationMutationOptions(workspace.workspaceId, client)
	);
	const revoke = createMutation(() =>
		workspaceInvitationRevokeMutationOptions(workspace.workspaceId, client)
	);
	const busy = $derived(create.isPending || revoke.isPending);
	const roles = $derived(workspace.view?.allowed_invitation_roles ?? []);
	let username = $state('');
	let role = $state<components['schemas']['WorkspaceInvitationRole']>('viewer');
	let days = $state(7);
	let oneTimeInvitation = $state<components['schemas']['WorkspaceInvitationCreatedView'] | null>(
		null
	);
	let error = $state('');
	let notice = $state('');
	$effect(() => {
		if (!roles.includes(role) && roles[0]) role = roles[0];
	});
	async function invite() {
		if (busy || !roles.includes(role) || !username.trim()) return;
		error = '';
		notice = '';
		try {
			oneTimeInvitation = await create.mutateAsync({
				username: username.trim(),
				role,
				expires_at: new Date(Date.now() + days * 86_400_000).toISOString()
			});
			username = '';
			notice = $t('Invitation created. Copy this token now; it will not be shown again.');
		} catch (reason) {
			error = apiErrorMessage(reason, 'Unable to create invitation');
		}
	}
	async function revokeInvitation(id: string) {
		if (busy) return;
		error = '';
		notice = '';
		try {
			await revoke.mutateAsync(id);
			if (oneTimeInvitation?.id === id) oneTimeInvitation = null;
			notice = $t('Invitation revoked');
		} catch (reason) {
			error = apiErrorMessage(reason, 'Workspace action failed');
		}
	}
	async function copyLink() {
		if (!oneTimeInvitation) return;
		error = '';
		notice = '';
		try {
			await navigator.clipboard.writeText(`${location.origin}/invite/${oneTimeInvitation.token}`);
			notice = $t('Invitation link copied');
		} catch {
			error = $t('Unable to copy the invitation link. Select and copy it manually.');
		}
	}
</script>

<section class="grid grid-cols-1 gap-6" aria-labelledby="workspace-invitations-heading">
	<div>
		<h2 id="workspace-invitations-heading" class="text-xl font-semibold">{$t('Invitations')}</h2>
		<p class="mt-1 text-sm text-surface-700-300">
			{$t('Invite an existing user to join this workspace.')}
		</p>
	</div>
	{#if workspace.can('workspace_invitation.read')}
		{#if roles.length > 0}
			<Panel>
				<form
					class="grid grid-cols-1 gap-4 sm:grid-cols-2"
					onsubmit={(event) => {
						event.preventDefault();
						void invite();
					}}
				>
					<label class="grid grid-cols-1 gap-1 sm:col-span-2"
						>{$t('Exact username')}<input
							class="input"
							bind:value={username}
							required
							disabled={busy}
						/></label
					>
					<label class="grid grid-cols-1 gap-1"
						>{$t('Role')}<select class="select" bind:value={role} disabled={busy}
							>{#each roles as choice (choice)}<option value={choice}
									>{$t(domainLabel(choice))}</option
								>{/each}</select
						></label
					>
					<label class="grid grid-cols-1 gap-1"
						>{$t('Expires in days')}<input
							class="input"
							type="number"
							min="1"
							max="365"
							required
							bind:value={days}
							disabled={busy}
						/></label
					>
					<div class="sm:col-span-2">
						<Button type="submit" variant="filled" disabled={busy || !username.trim()}
							>{$t('Create invitation')}</Button
						>
					</div>
				</form>
			</Panel>
		{/if}
		<StatusNotice {error} {notice} />
		{#if oneTimeInvitation}
			<Panel class="grid grid-cols-1 justify-items-start gap-3">
				<code class="break-all">{location.origin}/invite/{oneTimeInvitation.token}</code>
				<Button size="sm" disabled={busy} onclick={() => void copyLink()}
					>{$t('Copy one-time link')}</Button
				>
			</Panel>
		{/if}
		{#if invitations.isPending}<p class="text-surface-700-300">{$t('Loading invitations…')}</p>
		{:else if invitations.isError}<Notice variant="error"
				>{$t('Unable to load invitations.')}
				<Button disabled={invitations.isFetching} onclick={() => void invitations.refetch()}
					>{$t('Retry')}</Button
				></Notice
			>
		{:else if invitations.data?.length}
			<Panel padding="none"
				><ul class="divide-y divide-surface-300-700">
					{#each invitations.data as invitation (invitation.id)}
						<li class="flex flex-wrap items-center justify-between gap-3 p-4">
							<div class="min-w-0">
								<strong class="break-all">{invitation.username}</strong>
								<p class="text-sm text-surface-700-300">
									{$t(domainLabel(invitation.role))} · {$t('expires')}
									{$dateFormat.format(new Date(invitation.expires_at))}
								</p>
							</div>
							{#if workspace.can('workspace_invitation.revoke')}<Button
									size="sm"
									disabled={busy}
									onclick={() => void revokeInvitation(invitation.id)}>{$t('Revoke')}</Button
								>{/if}
						</li>
					{/each}
				</ul></Panel
			>
		{:else}<Notice>{$t('No pending invitations.')}</Notice>{/if}
	{:else}<Notice>{$t('Invitations are not available for this workspace.')}</Notice>{/if}
</section>
