<script lang="ts">
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';
	import { workspaceKeys } from '$lib/workspaces/keys';
	import { apiErrorMessage } from '$lib/api/errors';
	import Notice from '$lib/design/Notice.svelte';
	import Button from '$lib/design/Button.svelte';
	import { t } from '$lib/i18n';
	import { domainLabel } from '$lib/domain-labels';

	const workspace = getWorkspaceContext();
	const api = workspace.api;
	const client = useQueryClient();
	const directoryMembers = createQuery(() => ({
		queryKey: workspaceKeys.members(workspace.workspaceId),
		queryFn: ({ signal }: { signal: AbortSignal }) =>
			api.request('GET', '/workspaces/{workspace_id}/members', { signal }),
		enabled: Boolean(workspace.view) && !workspace.can('workspace.members.manage')
	}));
	const governanceMembers = createQuery(() => ({
		queryKey: workspaceKeys.governanceMembers(workspace.workspaceId),
		queryFn: ({ signal }: { signal: AbortSignal }) =>
			api.request('GET', '/workspaces/{workspace_id}/governance/members', { signal }),
		enabled: Boolean(workspace.view) && workspace.can('workspace.members.manage')
	}));
	const invitations = createQuery(() => ({
		queryKey: workspaceKeys.invitations(workspace.workspaceId),
		queryFn: ({ signal }: { signal: AbortSignal }) =>
			api.request('GET', '/workspaces/{workspace_id}/invitations', { signal }),
		enabled: workspace.can('workspace.members.manage')
	}));
	let name = $state(workspace.view?.name ?? '');
	let inviteUsername = $state('');
	let inviteRole = $state<'editor' | 'reviewer' | 'viewer'>('viewer');
	let inviteDays = $state(7);
	let oneTimeToken = $state('');
	let message = $state('');
	let error = $state('');
	let busyId = $state('');

	async function run(id: string, action: () => Promise<unknown>, success: string) {
		busyId = id;
		message = '';
		error = '';
		try {
			await action();
			message = success;
			await Promise.all([
				workspace.can('workspace.members.manage')
					? governanceMembers.refetch()
					: directoryMembers.refetch(),
				workspace.can('workspace.members.manage') ? invitations.refetch() : Promise.resolve(),
				client.invalidateQueries({ queryKey: workspaceKeys.root(workspace.workspaceId) })
			]);
		} catch (reason) {
			error = apiErrorMessage(reason, 'Workspace action failed');
		} finally {
			busyId = '';
		}
	}

	async function saveName() {
		await run(
			'rename',
			() => api.request('PATCH', '/workspaces/{workspace_id}', { body: { name: name.trim() } }),
			$t('Workspace name updated')
		);
	}
	async function createInvitation() {
		busyId = 'invite';
		error = '';
		message = '';
		try {
			const expiresAt = new Date(Date.now() + Number(inviteDays) * 86_400_000).toISOString();
			const created = await api.request('POST', '/workspaces/{workspace_id}/invitations', {
				body: { username: inviteUsername.trim(), role: inviteRole, expires_at: expiresAt }
			});
			oneTimeToken = created.token;
			inviteUsername = '';
			message = $t('Invitation created. Copy this token now; it will not be shown again.');
			await invitations.refetch();
		} catch (reason) {
			error = apiErrorMessage(reason, 'Unable to create invitation');
		} finally {
			busyId = '';
		}
	}
	async function copyToken() {
		await navigator.clipboard.writeText(`${location.origin}/invite/${oneTimeToken}`);
		message = $t('Invitation link copied');
	}
	async function deleteWorkspace() {
		if (
			confirm(
				`Permanently delete “${workspace.view?.name ?? 'this Workspace'}” and its content? This cannot be undone.`
			)
		)
			await run(
				'delete',
				() => api.request('DELETE', '/workspaces/{workspace_id}'),
				$t('Workspace deleted')
			);
	}
	function confirmOwnershipTransfer(username: string): boolean {
		return confirm(
			`Transfer Workspace ownership to ${username}? You will lose owner-only governance capabilities.`
		);
	}
</script>

<svelte:head><title>{$t('Workspace settings · Quirebase')}</title></svelte:head>
<section class="grid grid-cols-1 gap-8">
	<header class="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
		<div class="grid grid-cols-1 gap-2">
			<p class="text-sm font-semibold text-primary-700-300">{$t('Workspace governance')}</p>
			<h1 class="text-3xl font-bold">{workspace.view?.name ?? $t('Workspace settings')}</h1>
			<p class="text-sm text-surface-600-400">
				{$t('Your role:')}
				{workspace.view?.current_role ? $t(domainLabel(workspace.view.current_role)) : '—'} · {$t(
					'Status:'
				)}
				{workspace.view?.state ? $t(domainLabel(workspace.view.state)) : '—'}
			</p>
		</div>
	</header>
	{#if error}<Notice variant="error">{error}</Notice>{/if}{#if message}<Notice>{message}</Notice
		>{/if}
	<section
		class="grid max-w-2xl grid-cols-1 gap-3 rounded-container border border-surface-300-700 bg-surface-50-950 p-5"
		aria-labelledby="workspace-general-heading"
	>
		<div class="grid grid-cols-1 gap-1">
			<h2 id="workspace-general-heading" class="text-xl font-semibold">{$t('General')}</h2>
			<p class="text-sm text-surface-600-400">
				{$t('Update the name members see across this workspace.')}
			</p>
		</div>
		<label class="grid grid-cols-1 gap-1"
			>{$t('Name')}<input
				class="input"
				bind:value={name}
				maxlength="240"
				disabled={!workspace.can('workspace.settings.manage')}
			/></label
		>
		{#if workspace.can('workspace.settings.manage')}<div>
				<Button
					variant="filled"
					disabled={busyId !== '' || !name.trim() || name.trim() === workspace.view?.name}
					onclick={() => void saveName()}>{$t('Save name')}</Button
				>
			</div>{/if}
	</section>
	{#if workspace.can('workspace.archive') || workspace.can('workspace.delete')}
		<section
			class="grid max-w-2xl grid-cols-1 gap-4 rounded-container border border-surface-300-700 bg-surface-50-950 p-5"
			aria-labelledby="workspace-lifecycle-heading"
		>
			<div class="grid grid-cols-1 gap-1">
				<h2 id="workspace-lifecycle-heading" class="text-xl font-semibold">{$t('Lifecycle')}</h2>
				<p class="text-sm text-surface-600-400">
					{$t(
						'Archive pauses normal changes while preserving readable content. You can restore it later.'
					)}
				</p>
			</div>
			<div class="flex flex-wrap gap-2">
				{#if workspace.can('workspace.archive') && workspace.view?.state === 'active'}<Button
						variant="warning"
						disabled={busyId !== ''}
						onclick={() => {
							if (
								confirm('Archive this Workspace? Members will retain read access to its content.')
							)
								void run(
									'archive',
									() => api.request('POST', '/workspaces/{workspace_id}/archive'),
									$t('Workspace archived')
								);
						}}>{$t('Archive workspace')}</Button
					>{/if}
				{#if workspace.can('workspace.archive') && workspace.view?.state === 'archived'}<Button
						variant="success"
						disabled={busyId !== ''}
						onclick={() =>
							void run(
								'restore',
								() => api.request('POST', '/workspaces/{workspace_id}/restore'),
								$t('Workspace restored')
							)}>{$t('Restore workspace')}</Button
					>{/if}
			</div>
		</section>
	{/if}
	{#if workspace.can('workspace.delete')}
		<section
			class="grid max-w-2xl grid-cols-1 gap-3 rounded-container border border-error-500/40 bg-error-50-950/30 p-5"
			aria-labelledby="workspace-delete-heading"
		>
			<div class="grid grid-cols-1 gap-1">
				<h2 id="workspace-delete-heading" class="text-xl font-semibold">
					{$t('Permanent deletion')}
				</h2>
				<p class="text-sm text-surface-600-400">
					{$t(
						'This permanently removes the workspace and its content after the archive retention period. This cannot be undone.'
					)}
				</p>
			</div>
			<div>
				<Button
					variant="danger-filled"
					disabled={busyId !== '' || workspace.view?.state !== 'archived'}
					onclick={() => void deleteWorkspace()}>{$t('Permanently delete workspace')}</Button
				>
			</div>
		</section>
	{/if}
	{#if workspace.can('workspace.members.manage')}<section class="grid grid-cols-1 gap-3">
			<div>
				<h2 class="text-xl font-semibold">{$t('Members')}</h2>
				<p class="text-sm text-surface-600-400">
					{$t('Effective Workspace capabilities determine which governance actions are available.')}
				</p>
			</div>
			{#if governanceMembers.isPending}<p>
					{$t('Loading members…')}
				</p>{:else if governanceMembers.isError}<Notice variant="error"
					>{$t('Unable to load members.')}</Notice
				>{:else}
				<div
					class="overflow-x-auto rounded-container border border-surface-300-700 bg-surface-50-950"
				>
					<table class="w-full text-left text-sm">
						<thead
							><tr
								><th class="p-3">{$t('Username')}</th><th class="p-3">{$t('Role')}</th><th
									class="p-3">{$t('State')}</th
								><th class="p-3">{$t('Actions')}</th></tr
							></thead
						><tbody>
							{#each governanceMembers.data ?? [] as member (member.membership_id)}<tr
									class="border-t border-surface-300-700"
									><td class="p-3">{member.username}</td><td class="p-3"
										>{$t(domainLabel(member.role))}</td
									><td class="p-3">{$t(domainLabel(member.state))}</td><td
										class="flex flex-wrap gap-2 p-3"
									>
										{#if member.role !== 'owner' && ((member.role === 'admin' && workspace.can('workspace.admins.manage')) || (member.role !== 'admin' && workspace.can('workspace.members.manage')))}
											<select
												aria-label={$t('Role for {username}', { username: member.username })}
												value={member.role}
												onchange={(event) => {
													const role = event.currentTarget.value as
														'admin' | 'editor' | 'reviewer' | 'viewer';
													void run(
														`role:${member.membership_id}`,
														() =>
															api.request(
																'PUT',
																'/workspaces/{workspace_id}/members/{membership_id}/role',
																{
																	params: { path: { membership_id: member.membership_id } },
																	body: { role }
																}
															),
														$t('Member role updated')
													);
												}}
												><option value="admin" disabled={!workspace.can('workspace.admins.manage')}
													>{$t('admin')}</option
												><option value="editor">{$t('editor')}</option><option value="reviewer"
													>{$t('reviewer')}</option
												><option value="viewer">{$t('viewer')}</option></select
											>
											{#if member.state === 'active'}<Button
													size="sm"
													variant="tonal"
													disabled={busyId !== ''}
													onclick={() =>
														void run(
															`suspend:${member.membership_id}`,
															() =>
																api.request(
																	'POST',
																	'/workspaces/{workspace_id}/members/{membership_id}/suspend',
																	{ params: { path: { membership_id: member.membership_id } } }
																),
															$t('Member suspended')
														)}>{$t('Suspend')}</Button
												>{:else}<Button
													size="sm"
													variant="tonal"
													disabled={busyId !== ''}
													onclick={() =>
														void run(
															`reactivate:${member.membership_id}`,
															() =>
																api.request(
																	'POST',
																	'/workspaces/{workspace_id}/members/{membership_id}/reactivate',
																	{ params: { path: { membership_id: member.membership_id } } }
																),
															$t('Member reactivated')
														)}>{$t('Reactivate')}</Button
												>{/if}
											{#if workspace.can('workspace.ownership.transfer') && member.state === 'active'}<Button
													size="sm"
													variant="tonal"
													disabled={busyId !== ''}
													onclick={() => {
														if (confirmOwnershipTransfer(member.username))
															void run(
																`transfer:${member.membership_id}`,
																() =>
																	api.request(
																		'POST',
																		'/workspaces/{workspace_id}/ownership/{membership_id}',
																		{ params: { path: { membership_id: member.membership_id } } }
																	),
																$t('Ownership transferred')
															);
													}}>{$t('Transfer ownership')}</Button
												>{/if}
											<Button
												size="sm"
												variant="tonal"
												disabled={busyId !== ''}
												onclick={() => {
													if (confirm(`Terminate ${member.username}'s Workspace membership?`))
														void run(
															`terminate:${member.membership_id}`,
															() =>
																api.request(
																	'DELETE',
																	'/workspaces/{workspace_id}/members/{membership_id}',
																	{ params: { path: { membership_id: member.membership_id } } }
																),
															$t('Member removed')
														);
												}}>{$t('Terminate')}</Button
											>
										{/if}
									</td></tr
								>{/each}</tbody
						>
					</table>
				</div>
			{/if}
		</section>
	{:else}
		<section class="grid grid-cols-1 gap-3">
			<div>
				<h2 class="text-xl font-semibold">{$t('Members')}</h2>
			</div>
			{#if directoryMembers.isPending}
				<p>{$t('Loading members…')}</p>
			{:else if directoryMembers.isError}
				<Notice variant="error">{$t('Unable to load members.')}</Notice>
			{:else}
				<div
					class="overflow-x-auto rounded-container border border-surface-300-700 bg-surface-50-950"
				>
					<table class="w-full text-left text-sm">
						<thead>
							<tr>
								<th class="p-3">{$t('Username')}</th>
								<th class="p-3">{$t('Role')}</th>
							</tr>
						</thead>
						<tbody>
							{#each directoryMembers.data ?? [] as member (member.user_id)}
								<tr class="border-t border-surface-300-700">
									<td class="p-3">{member.username}</td>
									<td class="p-3">{$t(domainLabel(member.role))}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</section>
	{/if}
	{#if workspace.can('workspace.members.manage')}
		<section
			class="grid grid-cols-1 gap-4 rounded-container border border-surface-300-700 bg-surface-50-950 p-5"
		>
			<h2 class="text-xl font-semibold">{$t('Invitations')}</h2>
			<form
				class="grid grid-cols-1 gap-3 md:grid-cols-4"
				onsubmit={(event) => {
					event.preventDefault();
					void createInvitation();
				}}
			>
				<label class="grid grid-cols-1 gap-1 md:col-span-2"
					>{$t('Exact username')}<input class="input" bind:value={inviteUsername} required /></label
				>
				<label class="grid grid-cols-1 gap-1"
					>{$t('Role')}<select bind:value={inviteRole}
						><option value="viewer">{$t('viewer')}</option><option value="reviewer"
							>{$t('reviewer')}</option
						><option value="editor">{$t('editor')}</option></select
					></label
				>
				<label class="grid grid-cols-1 gap-1"
					>{$t('Expires in days')}<input
						class="input"
						type="number"
						min="1"
						max="365"
						bind:value={inviteDays}
					/></label
				>
				<Button type="submit" disabled={busyId !== '' || !inviteUsername.trim()}
					>{$t('Create invitation')}</Button
				>
			</form>
			{#if oneTimeToken}<div
					class="flex flex-wrap items-center gap-2 rounded-md bg-surface-100-900 p-3"
				>
					<code class="break-all">{location.origin}/invite/{oneTimeToken}</code><Button
						size="sm"
						onclick={() => void copyToken()}>{$t('Copy one-time link')}</Button
					>
				</div>{/if}
			{#if invitations.data?.length}<ul class="grid grid-cols-1 gap-2">
					{#each invitations.data as invitation (invitation.id)}<li
							class="flex flex-wrap items-center justify-between gap-2 border-t border-surface-300-700 py-2"
						>
							<span
								>{invitation.username} · {$t(domainLabel(invitation.role))} · {$t('expires')}
								{new Date(invitation.expires_at).toLocaleDateString()}</span
							><Button
								size="sm"
								variant="tonal"
								disabled={busyId !== ''}
								onclick={() =>
									void run(
										`revoke:${invitation.id}`,
										() =>
											api.request(
												'DELETE',
												'/workspaces/{workspace_id}/invitations/{invitation_id}',
												{ params: { path: { invitation_id: invitation.id } } }
											),
										$t('Invitation revoked')
									)}>{$t('Revoke')}</Button
							>
						</li>{/each}
				</ul>{/if}
		</section>
	{/if}
</section>
